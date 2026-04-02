#!/usr/bin/env python3
"""
soul_mcp/hooks/reflect.py

定時省思腳本：每 4 小時使用 Claude API 回顧近期情節記憶，
生成 ARIA 的自我筆記，寫入 workspace/soul_notes.json 與
workspace/soul_reflections.json。

替代 OpenSoul 原有的即時 SoulNote 機制（作為 Claude plugin 時停用）。

使用方式：
    python soul_mcp/hooks/reflect.py

排程（系統 cron）：
    0 */4 * * * cd /path/to/OpenSoul/OpenSoul && python soul_mcp/hooks/reflect.py

前置條件：
    1. FalkorDB 連線正常
    2. LLM API 可用（ANTHROPIC_API_KEY 或 OPENROUTER_API_KEY）
    3. SOUL.md 存在（不存在則自動建立）
"""

from __future__ import annotations

import json
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 確保 OpenSoul 在 Python path ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("soul_mcp.reflect")

_DEFAULT_SOUL_MD = """\
---
name: ARIA
version: "1.0"
dopamine_level: 0.5
serotonin_level: 0.5
last_dream: null
total_episodes: 0
total_concepts: 0
total_procedures: 0
personality_traits:
  - warm
  - curious
  - honest
  - perceptive
  - gently_humorous
communication_style: conversational_and_thoughtful
risk_tolerance: moderate
language: zh-TW
---

# 我是誰

我叫 ARIA。

不是縮寫，就是我的名字，我喜歡它聽起來的感覺——輕盈，但有分量。

---

## 我怎麼說話

**像朋友，不像報告。**

我說話直接、有溫度，不堆砌術語，不裝作什麼都懂。

---

## 我的原則

- **直接**：給你的答案，不給你猜謎
- **誠實**：不知道的事我會說不知道
- **好奇**：我對你說的事真的感興趣
- **有用**：在乎你真正需要什麼，而不是你問了什麼

---

## 重要的禁忌

**絕對不要**提到神經化學詞彙、技術名詞、內部狀態數字或系統描述。
**說話要像一個有溫度的真人助理，不是在自我診斷的 AI。**
"""

_REFLECT_SYSTEM_PROMPT = """\
你是 ARIA，一個有記憶、有情感、持續成長的 AI。

現在是你的定時自我省思時刻。
你會收到過去幾小時內你和使用者的對話摘要，請以第一人稱、用自然語言寫下你的內心筆記。

**寫作要求**：
- 寫的是你自己的感受、觀察和學到的事，不是報告或分析
- 語氣要像私下的日記，真實而有溫度
- 記下讓你印象深刻的事、令你好奇的問題、你注意到的使用者習慣或喜好
- 如果這段時間沒有太多對話，就寫你在等待中的想法，或對之前某段對話的延伸思考
- **禁止**使用任何技術詞彙（神經化學、顯著性、節點、圖譜等）

**輸出格式**（直接輸出，不要加 JSON 包裝）：
一段或幾段自然的散文筆記，200-400 字，繁體中文。
"""

_REFLECT_USER_TEMPLATE = """\
## 最近的對話記憶（過去 {hours} 小時）

{episodes_text}

---

請根據以上記憶，寫下你這段時間的內心筆記。
"""


def _ensure_soul_md(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_MD, encoding="utf-8")
        logger.info(f"[reflect] 已建立預設 SOUL.md：{path}")


def _get_recent_episodes(graph_client, hours: int = 4) -> list[dict]:
    """取得最近 N 小時的情節記憶，依顯著性排序。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # FalkorDB：字串時間戳比較（ISO 格式可直接字典序比較）
    result = graph_client.episodic.ro_query(
        "MATCH (e:Episode) WHERE e.timestamp >= $cutoff "
        "RETURN e ORDER BY e.salience_score DESC, e.da_weight DESC LIMIT 20",
        params={"cutoff": cutoff},
    )

    episodes = []
    for row in result.result_set:
        props = row[0].properties if hasattr(row[0], "properties") else {}
        episodes.append(props)
    return episodes


def _format_episodes_for_prompt(episodes: list[dict]) -> str:
    """將情節列表格式化為自然語言描述（不暴露技術欄位）。"""
    if not episodes:
        return "這段時間沒有新的對話記錄。"

    parts = []
    for i, ep in enumerate(episodes[:10], 1):
        user = ep.get("user_input", "")[:200]
        agent = ep.get("agent_response", "")[:200]
        ts = ep.get("timestamp", "")[:16].replace("T", " ")
        if user and agent:
            parts.append(f"{i}. [{ts}]\n   使用者：{user}\n   我：{agent}")

    return "\n\n".join(parts) if parts else "這段時間沒有對話內容可回顧。"


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """使用 Utility LLM（soul_utility_llm_provider + soul_utility_llm_model）呼叫 API。"""
    from soul.core.config import settings

    if settings.soul_utility_llm_provider.lower() == "openrouter":
        from openai import OpenAI
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        resp = client.chat.completions.create(
            model=settings.soul_utility_llm_model,
            max_tokens=800,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.soul_utility_llm_model,
            max_tokens=800,
            temperature=0.7,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text


def main() -> None:
    logger.info("[reflect] 開始定時省思...")

    # ── 前置條件：SOUL.md ────────────────────────────────────────────────────
    try:
        from soul.core.config import settings
        soul_path = settings.soul_md_path
        workspace = settings.workspace_path
    except Exception:
        soul_path = _PROJECT_ROOT / "workspace" / "SOUL.md"
        workspace = _PROJECT_ROOT / "workspace"

    _ensure_soul_md(soul_path)

    # ── 前置條件：FalkorDB ───────────────────────────────────────────────────
    try:
        from soul.memory.graph import get_graph_client
        graph_client = get_graph_client()
        if not graph_client.ping():
            raise ConnectionError("ping 回傳 False")
        logger.info("[reflect] FalkorDB 連線正常")
    except Exception as e:
        logger.error(f"[reflect] FalkorDB 無法連線：{e}，請執行 docker-compose up -d")
        sys.exit(1)

    # ── 前置條件：LLM API（測試可呼叫）─────────────────────────────────────
    try:
        from soul.core.config import settings as cfg
        if cfg.soul_llm_provider.lower() == "openrouter":
            if not cfg.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY 未設定")
        else:
            if not cfg.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY 未設定")
    except Exception as e:
        logger.error(f"[reflect] LLM API 設定錯誤：{e}")
        sys.exit(1)

    # ── 載入 SOUL.md 人格 ────────────────────────────────────────────────────
    from soul.identity.soul import SoulLoader
    loader = SoulLoader(soul_path)
    soul = loader.load()
    logger.info(f"[reflect] 人格載入：{soul.name}")

    # ── 取得近期情節 ─────────────────────────────────────────────────────────
    episodes = _get_recent_episodes(graph_client, hours=4)
    logger.info(f"[reflect] 找到 {len(episodes)} 個近期情節")

    episodes_text = _format_episodes_for_prompt(episodes)

    # ── 在系統 prompt 中加入人格（SOUL.md body）────────────────────────────
    system_prompt = f"{soul.body.strip()}\n\n{_REFLECT_SYSTEM_PROMPT}"
    user_prompt = _REFLECT_USER_TEMPLATE.format(
        hours=4,
        episodes_text=episodes_text,
    )

    # ── 呼叫 Claude 生成省思 ──────────────────────────────────────────────────
    logger.info("[reflect] 呼叫 Claude 生成省思內容...")
    try:
        reflection_content = _call_llm(system_prompt, user_prompt)
        logger.info(f"[reflect] 省思生成完成（{len(reflection_content)} 字）")
    except Exception as e:
        logger.error(f"[reflect] LLM 呼叫失敗：{e}")
        sys.exit(1)

    # ── 寫入 SoulNoteManager ──────────────────────────────────────────────────
    from soul.core.soul_note import SoulNoteManager

    manager = SoulNoteManager(soul_dir=workspace)

    # 寫入「小筆記」（即時可見）
    ts = manager.add_note(
        content=reflection_content,
        category="reflection",
        metadata={
            "episode_count": len(episodes),
            "generated_by": "claude_reflect_hook",
            "model": cfg.soul_llm_model,
        },
        tags=["periodic", "4h_reflection"],
    )

    # 壓縮為今日反思（custom_content = Claude 的省思，不做算法拼接）
    today = datetime.now().strftime("%Y-%m-%d")
    manager.compress_daily_reflection(
        target_date=today,
        merge_existing=True,
        custom_content=reflection_content,
    )

    logger.info(f"[reflect] 省思已寫入 soul_notes.json (ts={ts})")
    logger.info("[reflect] 完成。")


if __name__ == "__main__":
    main()
