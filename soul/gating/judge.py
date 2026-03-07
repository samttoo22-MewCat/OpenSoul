"""
soul/gating/judge.py

裁判模型 (Judge Agent)：利用另一個 LLM 呼叫來對 ARIA 的回應進行「認知審核」。
對應大腦分區：眶額葉皮質 (Orbitofrontal Cortex, OFC) — 行為價值評估與錯誤偵測。

職責：
  1. 檢測「言行一致性」：如果文字提到修改設定，是否真的呼叫了工具？
  2. 檢測「工具濫用」：是否嘗試用 web_fetch 抓取在地指令？
  3. 提供修正建議給主 Agent。
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from soul.affect.neurochem import NeurochemState
from soul.core.config import settings

logger = logging.getLogger("soul.judge")

@dataclass
class JudgmentResult:
    """裁判模型的審核結果。"""
    is_valid: bool = True           # 是否通過審核
    score: float = 1.0              # 信心分數 (0.0 ~ 1.0)
    critique: str = ""              # 批評或建議
    action_required: str = "pass"   # pass, revise, suppress

class JudgeAgent:
    """
    工具決策者 (Decider)：負責在 ARIA 思考前，決定是否需要工具以及該使用哪個工具。
    它是系統中唯一的工具調度入口。
    """
    
    _DECIDER_PROMPT = """你是一個系統中的「唯一工具決策者」。
你負責在主模型 (ARIA) 回覆前，分析使用者需求並決定是否需要呼叫外部工具。

### 核心原則：
1. **實體行為優先 (重要)**：
   - 任何涉及 **「修改檔案」** (如 `edit-soul` 修改 `SOUL.md`)、**「存取即時數據」** (如 `gmail` 讀取郵件, `browser-control` 瀏覽網頁) 或 **「實體系統操作」** 的需求，**必須** 調用對應工具。
   - ARIA 的內建知識僅限於「語言回答」，無法真正改變系統狀態。對於持久化修改請求，決不能回傳 "none"。
2. **區分對話與執行**：
   - 使用者說「幫我改設定」或「幫我查郵件」時，ARIA 嘴巴說「好的」並不等於完成任務。你必須選中對應工具，讓系統真正執行腳本。
3. **精準匹配**：根據工具的「功能描述」與「參數手冊」來判斷。如果你決定呼叫某個工具，請同時告訴 ARIA 為什麼以及該如何使用。
4. **最小化非必要調用**：只有在單純的學術問答、創意寫作或一般閒聊（不涉及系統狀態或外部資訊）時，才回傳 "none"。

### 輸出格式：
你必須回傳一個 JSON 格式：
{
  "recommended_tool": "工具名稱 (如 browser-control, gmail) 或 'none'",
  "reasoning": "為什麼選擇這個工具。如果涉及檔案修改，請註明：'這是持久化修改，必須調用實體工具而非僅靠對話。'",
  "confidence": 0.0 到 1.0 之間的信心分數
}

只回傳 JSON，不要有其他文字。"""

    def __init__(self, llm_client: Any, provider: str = "anthropic") -> None:
        self._llm = llm_client
        self._provider = provider.lower()
        self._available_tools_cache = None

    def discover_available_tools(self) -> list[dict[str, Any]]:
        """
        探測可用的工具/技能，並包含基本的描述資訊。
        """
        if self._available_tools_cache is not None:
            return self._available_tools_cache

        tools = []
        try:
            import os
            if "OPENCLAW_SKILLS_PATH" in os.environ:
                skills_dir = Path(os.environ["OPENCLAW_SKILLS_PATH"])
            else:
                skills_dir = Path(settings.soul_project_root) / "openclaw" / "skills"

            if skills_dir.exists():
                for skill_folder in skills_dir.iterdir():
                    if skill_folder.is_dir() and not skill_folder.name.startswith("_"):
                        skill_name = skill_folder.name
                        skill_md = skill_folder / "SKILL.md"
                        description = f"OpenClaw skill: {skill_name}"
                        
                        if skill_md.exists():
                            try:
                                content = skill_md.read_text(encoding="utf-8")
                                lines = content.split("\n")
                                if lines and lines[0].strip() == "---":
                                    for i in range(1, len(lines)):
                                        if lines[i].strip() == "---":
                                            for line in lines[1:i]:
                                                if line.startswith("description:"):
                                                    desc_val = line.split(":", 1)[1].strip().strip("\"'")
                                                    if desc_val:
                                                        description = desc_val
                                            break
                            except Exception: pass
                        
                        tools.append({
                            "name": skill_name,
                            "description": description,
                        })
        except Exception as e:
            logger.error(f"[Judge] 探測失敗：{e}")

        self._available_tools_cache = tools
        return tools

    def recommend_tool(
        self,
        user_input: str,
        available_tools_with_schemas: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        根據使用者需求與完整的 Schema 指引，決定唯一的工具。
        """
        # 建立詳細的工具說明字串，包含 Schema 知識
        tools_description = ""
        for tool in available_tools_with_schemas:
            # 🆕 魯棒性檢查：確保 tool 是字典
            if not isinstance(tool, dict):
                logger.warning(f"[Judge] 傳入的工具格式錯誤 (預期 dict，得到 {type(tool)}): {tool}")
                name = str(tool)
                desc = "未知工具"
                params = {}
            else:
                # 兼容處理：可能是 OpenAI 的 Schema 格式或是內部的簡單字典
                if "function" in tool:
                    # OpenAI 格式: {"type": "function", "function": {"name": "...", "description": "..."}}
                    func = tool["function"]
                    name = func.get("name", "unknown")
                    desc = func.get("description", "")
                    params = func.get("parameters", {}).get("properties", {})
                else:
                    # 內部格式: {"name": "...", "description": "...", "schema": {...}}
                    name = tool.get("name", "unknown")
                    desc = tool.get("description", "")
                    schema = tool.get("schema", {})
                    params = schema.get("function", {}).get("parameters", {}).get("properties", {})
            
            param_info = ", ".join(params.keys()) if params else "無參數"
            tools_description += f"- 【{name}】: {desc}\n  (可用參數: {param_info})\n"

        user_prompt = f"""
## 可用工具手冊：
{tools_description}

## 使用者目前需求：
{user_input}
"""
        try:
            raw = self._call_llm(user_prompt)
            data = self._parse_json(raw)
            return {
                "recommended_tool": data.get("recommended_tool", "none"),
                "reasoning": data.get("reasoning", ""),
                "confidence": float(data.get("confidence", 0.0))
            }
        except Exception as e:
            logger.error(f"[Judge] 決策失敗：{e}")
            return {"recommended_tool": "none", "reasoning": str(e), "confidence": 0.0}

    def _call_llm(self, user_prompt: str) -> str:
        if self._provider == "openrouter":
            resp = self._llm.chat.completions.create(
                model=settings.soul_llm_model,
                max_tokens=600,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": self._DECIDER_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content or "{}"
        else:
            msg = self._llm.messages.create(
                model=settings.soul_llm_model,
                max_tokens=600,
                temperature=0.0,
                system=self._DECIDER_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return msg.content[0].text

    def _parse_json(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except: pass
        return {}
