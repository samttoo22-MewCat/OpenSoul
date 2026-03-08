"""
soul/core/agent.py

SoulAgent：認知代理主迴圈。
整合 LLM（Claude）、EcphoryRAG、三記憶圖譜、人格系統（SOUL.md）。

執行順序（每次 user 輸入）：
  1. Embedding：取得查詢向量
  2. EcphoryRAG：從三圖譜觸發記憶
  3. 組合系統提示詞（人格 + 神經化學 + 記憶）
  4. 呼叫 Anthropic Claude 生成回覆
  5. SalienceEvaluator：計算顯著性 + 更新神經化學
  6. EpisodicMemory：寫入情節記憶（Engram）
  7. 後台概念提取 → SemanticMemory（Thread，不阻塞主流程）
  8. SoulLoader：持久化神經化學狀態至 SOUL.md
  9. 回傳 AgentResponse

對應大腦分區：前額葉（工作記憶整合）+ 邊緣系統（情緒調控）
"""

from __future__ import annotations

import re
import threading
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

def safe_print(msg: str):
    """針對 Windows CP950 編碼安全地打印訊息（降級 Emoji）。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        safe_msg = (
            msg.replace("🛠️", "[Tool]")
               .replace("📦", "[Args]")
               .replace("🧠", "[Brain]")
               .replace("📡", "[LLM]")
               .replace("👨‍⚖️", "[Judge]")
               .replace("📢", "[System]")
               .replace("⚠️", "[WARN]")
               .replace("✅", "[OK]")
               .replace("❌", "[ERR]")
        )
        try:
            print(safe_msg)
        except Exception:
            # 最後的防線：只打印 ascii 部分
            print(msg.encode("ascii", errors="replace").decode("ascii"))

import anthropic
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from soul.affect.neurochem import NeurochemState
from soul.affect.salience import SalienceEvaluator, SalienceSignals
from soul.affect.subconscious import SubconsciousAssessor, SubconsciousAssessment
from soul.core.config import settings
from soul.core.session import Session
from soul.gating.inhibitor import InhibitionAction, SubconsciousInhibitor
from soul.gating.judge import JudgeAgent, JudgmentResult
from soul.gating.verifier import ResponseVerifier
from soul.identity.soul import SoulIdentity, SoulLoader
from soul.memory.episodic import EpisodicMemory
from soul.memory.graph import GraphClient, get_graph_client, initialize_schemas
from soul.memory.procedural import ProceduralMemory
from soul.memory.retrieval import EcphoryRetrieval, MemoryContext
from soul.memory.semantic import SemanticMemory


# ── AgentResponse ──────────────────────────────────────────────────────────────

@dataclass
class AgentResponse:
    """
    SoulAgent.chat() 的回傳容器。

    欄位：
        text:           LLM 回覆文字
        episode_id:     本次寫入的 Episode 節點 ID
        memory_context: EcphoryRAG 觸發的記憶脈絡
        neurochem:      更新後的神經化學狀態快照（用於介面層顯示）
        session_id:     當前 Session ID
        was_cached:     是否來自快取（保留，目前恆為 False）
    """
    text: str
    episode_id: str
    session_id: str
    memory_context: MemoryContext = field(default_factory=MemoryContext)
    neurochem: dict[str, Any] = field(default_factory=dict)
    was_cached: bool = False
    gating_passed: bool = True          # False 表示最終回覆是 REVISE/SUPPRESS 降級結果
    gating_action: str = "pass"         # "pass" | "revise" | "suppress"
    gating_score: float = 1.0           # 最後一次驗證分數
    tool_calls: list[dict[str, Any]] | None = None  # LLM 發出的工具呼叫
    judge_decision: dict[str, Any] = field(default_factory=lambda: {"recommended_tool": "none", "reasoning": "", "confidence": 0.0})


# ── EmbeddingService ───────────────────────────────────────────────────────────

class EmbeddingService:
    """
    OpenAI text-embedding 封裝。

    預設模型：text-embedding-3-small（1536 維）
    帶 tenacity 重試機制（最多 3 次，指數退避）。
    """

    def __init__(self) -> None:
        # 根據 Provider 決定如何初始化客戶端
        if settings.soul_llm_provider.lower() == "openrouter":
            self._client = OpenAI(
                api_key=settings.openrouter_api_key or settings.openai_api_key,
                base_url=settings.openrouter_base_url
            )
        else:
            self._client = OpenAI(api_key=settings.openai_api_key)
            
        self._model = settings.soul_embedding_model
        self._dim = settings.soul_embedding_dim

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def embed(self, text: str) -> list[float]:
        """將文字轉為向量嵌入（帶重試）。"""
        text = text.strip().replace("\n", " ")
        if not text:
            return [0.0] * self._dim

        response = self._client.embeddings.create(
            input=text,
            model=self._model,
        )
        return response.data[0].embedding

    def zero_vector(self) -> list[float]:
        """回傳零向量（用於沒有 API 金鑰時的 fallback）。"""
        return [0.0] * self._dim


# ── SoulAgent ──────────────────────────────────────────────────────────────────

class SoulAgent:
    """
    openSOUL 認知代理主體。

    每個 SoulAgent 實例對應一個 SOUL.md 人格設定。
    可跨 Session 共享（神經化學狀態持久化至 SOUL.md）。

    Usage:
        agent = SoulAgent()
        session = Session()
        response = agent.chat("你好", session)
        print(response.text)
    """

    def __init__(
        self,
        workspace: Path | None = None,
        graph_client: GraphClient | None = None,
    ) -> None:
        # ── 人格載入 ────────────────────────────────────────────────────────
        self._loader = SoulLoader(
            soul_path=(workspace / "SOUL.md") if workspace else None
        )
        self._soul: SoulIdentity = self._loader.load()

        # ── 圖譜連線 ────────────────────────────────────────────────────────
        self._graph = graph_client or get_graph_client()
        initialize_schemas(self._graph)

        # ── 三記憶管理器 ────────────────────────────────────────────────────
        self._episodic = EpisodicMemory(self._graph)
        self._semantic = SemanticMemory(self._graph)
        self._procedural = ProceduralMemory(self._graph)

        # ── 檢索 + 顯著性 ───────────────────────────────────────────────────
        self._retrieval = EcphoryRetrieval(self._graph)
        self._salience = SalienceEvaluator()

        # ── 潛意識閘門（基底核 + 視丘）────────────────────────────────────
        self._verifier = ResponseVerifier()
        self._inhibitor = SubconsciousInhibitor()
        self._max_retries = settings.soul_verify_max_retries

        # ── Embedding + LLM 客戶端 ─────────────────────────────────────────
        self._embedder = EmbeddingService()
        self._model    = settings.soul_llm_model
        self._provider = settings.soul_llm_provider.lower()  # "anthropic" | "openrouter"

        if self._provider == "openrouter":
            # OpenRouter 使用 OpenAI 相容 API
            self._llm = OpenAI(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key or "no-key",
            )
            self._or_headers = {
                "HTTP-Referer": "https://opensoul.ai",
                "X-Title": settings.openrouter_app_name,
            }
        else:
            # 預設：直連 Anthropic
            self._llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            self._or_headers = {}

        # ── 潛意識評估器（LLM 自我內省）─────────────────────────────────
        self._subconscious = SubconsciousAssessor(
            llm_client=self._llm,
            provider=self._provider,
        )
        
        # 🆕 [裁判模型] 眶額葉皮質（行為價值評估）
        self._judge = JudgeAgent(
            llm_client=self._llm, # 目前使用與主模型相同的客戶端
            provider=self._provider
        )

    # ── 公開介面 ───────────────────────────────────────────────────────────────

    @property
    def soul(self) -> SoulIdentity:
        """取得當前 Agent 的人格身份（含神經化學狀態）。"""
        return self._soul

    def reload_soul(self) -> None:
        """重新從 SOUL.md 載入人格（不重建圖譜連線）。"""
        self._soul = self._loader.load()

    def chat(self, user_input: str, session: Session, tools: list[dict[str, Any]] | None = None) -> AgentResponse:
        """
        認知代理主迴圈：接收使用者輸入，整合記憶後生成回覆。

        Args:
            user_input: 使用者輸入文字
            session:    當前 Session 實例
            tools:      外部可用工具清單 (OpenAI 格式)

        Returns:
            AgentResponse 包含回覆文字、記憶脈絡、神經化學快照、及工具呼叫
        """
        neurochem = self._soul.neurochem

        # ── Step 1: 取得查詢向量 ────────────────────────────────────────────
        query_embedding = self._get_embedding(user_input)

        # ── Step 2: EcphoryRAG 觸發記憶 ────────────────────────────────────
        memory_ctx = self._retrieval.retrieve(
            query_embedding=query_embedding,
            serotonin=neurochem.serotonin,
            dopamine=neurochem.dopamine,
        )

        from concurrent.futures import ThreadPoolExecutor
        from soul.core.config import logger # Import logger here for use in this scope

        # ── Step 2.5: 預先並行處理（內省評估 + 工具裁判） ───────────────────────
        # 在進入主迴圈前，同時進行潛意識評估與第一次工具推薦，節省順序等待時間。
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 1. 潛意識評估（用於神經化學與顯著性更新）
            future_assessment = executor.submit(
                self._subconscious.assess,
                user_input=user_input,
                memory_ctx=memory_ctx,
                neurochem=neurochem,
            )
            
            # 2. 裁判模型推薦工具（第一次嘗試）
            future_decision = None
            current_tools = None # Initialize current_tools here
            if tools:
                future_decision = executor.submit(
                    self._judge.recommend_tool,
                    user_input=user_input,
                    available_tools_with_schemas=tools 
                )

            # 等待必要決策完成以進行後續步驟
            if future_decision:
                try:
                    decision = future_decision.result(timeout=15) # 設定超時防止卡死
                    rec_name = decision.get("recommended_tool", "none")
                    self.last_judge_decision = decision
                    
                    if rec_name != "none":
                        norm_rec = rec_name.replace("-", "_")
                        current_tools = [
                            t for t in tools 
                            if t.get("function", {}).get("name", "").replace("-", "_") == norm_rec
                        ]
                        if current_tools:
                            safe_print(f"🎯 [Judge 決策] 推薦使用工具：{rec_name}")
                            logger.info(f"👨‍⚖️ [Judge] 推薦工具: {rec_name} | 原因: {decision.get('reasoning')}")
                    else:
                        logger.info(f"👨‍⚖️ [Judge] 決策結果: 無需工具 | 原因: {decision.get('reasoning')}")
                except Exception as e:
                    logger.error(f"[Agent] 裁判模型並行呼叫失敗：{e}")
                    current_tools = None
            else:
                current_tools = None

        # ── Step 3: 組合系統提示詞 ─────────────────────────────────────────
        system_prompt = self._soul.build_system_prompt(
            memory_text=memory_ctx.to_text()
        )

        # ── Step 4: LLM 生成 + 潛意識閘門重試迴圈 ─────────────────────────
        #
        # 生成 → Verifier 驗證 → Inhibitor 決策：
        #   PASS     → 直接使用
        #   REVISE   → 加免責標記後使用
        #   SUPPRESS → on_failure() + 重試（最多 max_retries 次）
        #
        inhibit_result = None
        final_response_text = ""
        final_tool_calls: list[dict[str, Any]] | None = None
        error_feedback = "" # 🆕 用於存儲攔截或執行錯誤，回傳給 LLM

        for attempt in range(self._max_retries + 1):
            # from soul.core.config import logger # Already imported above
            logger.info(f"🧠 [Agent] ARIA 思考迴圈開始 (嘗試 #{attempt})...")
            
            # 如果是重試（attempt > 0）且有工具，則需要重新跑一次裁判（因為 user_input 可能帶有 error_feedback）
            if attempt > 0 and tools:
                decision = self._judge.recommend_tool(
                    user_input=f"{user_input}\n\n[修正引導: {error_feedback}]" if error_feedback else user_input,
                    available_tools_with_schemas=tools 
                )
                rec_name = decision.get("recommended_tool", "none")
                self.last_judge_decision = decision
                
                if rec_name != "none":
                    norm_rec = rec_name.replace("-", "_")
                    current_tools = [
                        t for t in tools 
                        if t.get("function", {}).get("name", "").replace("-", "_") == norm_rec
                    ]
                else:
                    current_tools = None

            # 🆕 如果有錯誤反饋，將其加入對話歷史
            current_user_input = user_input
            if error_feedback:
                current_user_input = f"{user_input}\n\n[系統通知：{error_feedback}]"
                logger.warning(f"📢 已將錯誤反饋傳送給 ARIA：{error_feedback}")
                error_feedback = "" # 發送後重置
            
            # 呼叫 LLM，注意此時 tools 是經由 Judge 過濾後的 current_tools
            response_text, tool_calls = self._call_llm(system_prompt, current_user_input, session, current_tools)
            
            # [Debug] 紀錄原始輸出的特徵
            resp_len = len(response_text) if response_text else 0
            logger.info(f"📡 [LLM] 原始回應長度: {resp_len} 字元 | 工具調用數: {len(tool_calls) if tool_calls else 0}")

            if tool_calls:
                new_tool_calls = []
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    args = tc.get("function", {}).get("arguments", "{}")
                    
                    # 只有在 Judge 允許的名單內才執行 (雙重保險)
                    if not current_tools or fn_name not in [t["function"]["name"] for t in current_tools]:
                        error_feedback = f"你呼叫了未經授權的工具 '{fn_name}'。請僅使用被核准的功能。"
                        continue

                    safe_print(f"\n🛠️  [ARIA 調用工具] 名稱: {fn_name}\n📦 [參數內容] {args}\n")
                    new_tool_calls.append(tc)
                
                if new_tool_calls:
                    final_response_text = response_text
                    final_tool_calls = new_tool_calls
                    break # 工具成功呼叫則結束循環
                elif error_feedback:
                    continue # 觸發重試
            
            # 基底核驗證 (僅針對文字內容)
            verify_result = self._verifier.verify(
                response_text=response_text,
                memory_ctx=memory_ctx,
                neurochem=neurochem,
            )

            # 視丘閘門決策
            inhibit_result = self._inhibitor.gate(
                response_text=response_text,
                verify_result=verify_result,
                neurochem=neurochem,
                attempt=attempt,
            )

            if not SubconsciousInhibitor.should_retry(inhibit_result, self._max_retries):
                final_response_text = inhibit_result.text
                break

            # SUPPRESS：重試前在 system_prompt 加入修正指引
            system_prompt = (
                system_prompt
                + f"\n\n[系統修正指引 #{attempt + 1}] "
                f"上一次回覆因信心不足被抑制（分數 {verify_result.score:.2f}）。"
                f"請確保回覆準確、有據可查。矛盾點：{'; '.join(verify_result.contradictions[:2])}"
            )
        else:
            # 重試耗盡，強制使用最後一次回覆（SUPPRESS 文字）
            final_response_text = inhibit_result.text if inhibit_result else response_text

        response_text = final_response_text

        # 若有工具呼叫，給予多巴胺獎勵 (操作外界的快感)
        if final_tool_calls:
            neurochem.on_discovery(novelty=0.4)

        # 取得潛意識評估結果（從並行任務中回收）
        try:
            assessment = future_assessment.result(timeout=10)
        except Exception as e:
            logger.error(f"[Agent] 潛意識評估並行呼叫失敗：{e}")
            assessment = SubconsciousAssessment() # 使用預設空值

        # ── Step 5: 計算顯著性 + 更新神經化學（使用 LLM 評估結果）─────────
        signals = SalienceSignals(
            task_complexity=assessment.complexity,
            novelty_score=assessment.novelty,
            error_occurred=assessment.uncertainty > 0.5,
        )
        # 情緒基調：正向 → on_success，負向 → on_failure
        if assessment.emotional_tone > 0.4:
            neurochem.on_success(reward=assessment.emotional_tone * 0.3)
        elif assessment.emotional_tone < -0.3:
            neurochem.on_failure(penalty=abs(assessment.emotional_tone) * 0.25)

        # 夢境共鳴：強共鳴 → on_discovery（深層新穎性）
        if assessment.dream_resonance > 0.5:
            neurochem.on_discovery(novelty=assessment.dream_resonance * 0.3)

        # 不確定性
        if assessment.uncertainty > 0.3:
            neurochem.on_uncertainty(level=assessment.uncertainty * 0.4)

        salience, da_weight, ht_weight = self._salience.evaluate(
            signals=signals,
            state=neurochem,
            user_message=user_input,
            agent_response=response_text,
        )
        self._salience.update_neurochem(neurochem, signals)

        # ── Step 6: 寫入情節記憶 ───────────────────────────────────────────
        # 🆕 優化：工具執行結果 (通常含有大量 JSON) 不寫入長期圖譜記憶，僅保留在 Session 歷史中
        is_tool_result = "[技能 " in user_input and " 執行結果]" in user_input
        
        episode_id = "temp_tool_result"
        if not is_tool_result:
            content_summary = _summarize(user_input, response_text)
            episode_id = self._episodic.write_episode(
                user_input=user_input,
                agent_response=response_text,
                session_id=session.session_id,
                content_summary=content_summary,
                embedding=query_embedding,
                da_weight=da_weight,
                ht_weight=ht_weight,
                salience_score=salience,
            )
        else:
            logger.info(f"🚫 [Memory] 檢測到工具回傳，跳過圖譜寫入以節省空間: {user_input[:50]}...")

        # ── Step 7: 後台概念提取（不阻塞主流程）─────────────────────────
        threading.Thread(
            target=self._extract_concepts_bg,
            args=(response_text, salience),
            daemon=True,
        ).start()

        # ── Step 8: 持久化神經化學狀態 + 後台生成潛意識感受 ────────────────────────
        self._loader.save_neurochem(neurochem)
        
        threading.Thread(
            target=self._generate_and_save_soul_note_bg,
            args=(user_input, response_text, neurochem.mode.value),
            daemon=True,
        ).start()

        # ── Session 記錄 ───────────────────────────────────────────────────
        session.turn_count += 1
        session.last_episode_id = episode_id
        session.log("user", user_input)
        session.log(
            "assistant",
            response_text[:200] + ("…" if len(response_text) > 200 else ""),
            metadata={"episode_id": episode_id[:8], "salience": salience},
        )

        # ── Step 9: 回傳 ───────────────────────────────────────────────────
        gating_action = inhibit_result.action.value if inhibit_result else "pass"
        gating_score  = inhibit_result.score        if inhibit_result else 1.0
        gating_passed = gating_action in ("pass", "revise")

        # ── Step 10: 內容消殺 (防偽過濾) ──────────────────────────────────────
        # 🆕 [硬性攔截] 防止 LLM 模仿標記。刪除所有包含 tool call 或 🛠️ 的手工代碼。
        import re
        patterns = [
            r"\[tool call:.*?\]",
            r"\[🛠️.*?實際執行.*?\]",
            r"\[系統已實際執行.*?\]"
        ]
        for pattern in patterns:
            response_text = re.sub(pattern, "", response_text, flags=re.IGNORECASE)
        
        # 🆕 [安全補丁] 確保文字不會被消殺個精光
        if not response_text.strip():
            logger.warning("⚠️  [消殺警告] 消殺後文字為空，已放棄過濾以確保回覆存在。")
            response_text = "（工具執行中...）" if final_tool_calls else "（思考中...）"
        
        response_text = response_text.strip()

        # 🆕 加入 Tool Call 的顯示標記 (使用者要求監控)
        tool_tag = "none"
        if final_tool_calls:
            try:
                # 提取工具名稱：可能是 function 欄位
                tools_used = []
                for tc in final_tool_calls:
                    if "function" in tc:
                        tools_used.append(tc["function"].get("name", "unknown"))
                    elif "name" in tc:
                        tools_used.append(tc["name"])
                if tools_used:
                    tool_tag = ", ".join(tools_used)
            except Exception:
                tool_tag = "detected"
        
        # 🔗 [新機制] 將工具執行與文字狀態同步打印到系統日誌面板
        from soul.core.config import logger as g_logger
        g_logger.info(f"📤 [Final Response] 工具狀態: {tool_tag} | 回應結尾截圖: ...{response_text[-30:].strip() if response_text else ''}")
        
        # 附加到文字末尾，只有在「真實」呼叫工具時才顯示 (使用者監控用)
        # 用比較醒目的 🛠️ 圖標區分系統紀錄與 LLM 的內文模仿
        if final_tool_calls and tool_tag != "none":
            response_text = f"{response_text}\n\n[🛠️ 系統已實際執行：{tool_tag}]"
            # 確保打印到後台控制台時也安全
            safe_print(f"✅ [工具執行報表] {tool_tag}")
        
        return AgentResponse(
            text=response_text,
            episode_id=episode_id,
            memory_context=memory_ctx,
            neurochem=neurochem.to_dict(),
            session_id=session.session_id,
            gating_passed=gating_passed,
            gating_action=gating_action,
            gating_score=gating_score,
            tool_calls=final_tool_calls,
            judge_decision=getattr(self, "last_judge_decision", {"recommended_tool": "none", "reasoning": "", "confidence": 0.0})
        )

    # ── Private Helpers ────────────────────────────────────────────────────────

    def _get_embedding(self, text: str) -> list[float]:
        """取得嵌入向量；若 API 金鑰未設定則回傳零向量。"""
        if not settings.openai_api_key:
            return self._embedder.zero_vector()
        try:
            return self._embedder.embed(text)
        except Exception:
            return self._embedder.zero_vector()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    def _call_llm(
        self,
        system_prompt: str,
        user_input: str,
        session: Session,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """
        呼叫 LLM 生成回覆，並支援 Tool Calling。
        回傳: (回應文字, tool_calls 清單)
        """
        history = _build_message_history(session, max_turns=10)
        history.append({"role": "user", "content": user_input})

        if self._provider == "openrouter":
            return self._call_openrouter(system_prompt, history, tools)
        else:
            return self._call_anthropic(system_prompt, history, tools)

    @staticmethod
    def _openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """將 OpenAI function-calling 格式轉換為 Anthropic tool_use 格式。

        OpenAI:  {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        """
        converted = []
        for tool in tools:
            fn = tool.get("function", {})
            converted.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return converted

    def _call_anthropic(self, system_prompt: str, history: list[dict], tools: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]] | None]:
        """透過 Anthropic SDK 呼叫 Claude，支援 tool_use。"""
        import logging
        _log = logging.getLogger("soul")

        kwargs: dict[str, Any] = {}
        if tools:
            anthropic_tools = self._openai_tools_to_anthropic(tools)
            kwargs["tools"] = anthropic_tools
            _log.info(f"Anthropic 傳入 {len(anthropic_tools)} 個工具")

        message = self._llm.messages.create(  # type: ignore[union-attr]
            model=self._model,
            max_tokens=4096,
            temperature=settings.soul_llm_temperature,
            system=system_prompt,
            messages=history,
            **kwargs,
        )

        # 解析回應：可能包含 text 和/或 tool_use blocks
        text_parts = []
        tc_dicts = None
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                if tc_dicts is None:
                    tc_dicts = []
                # 轉換回 OpenAI 格式，讓 api.py 的處理邏輯統一
                import json
                tc_dicts.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                })
                _log.info(f"Anthropic tool_use: {block.name}({block.input})")

        return "\n".join(text_parts), tc_dicts

    def _call_openrouter(self, system_prompt: str, history: list[dict], tools: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]] | None]:
        """透過 OpenRouter OpenAI 相容 API 呼叫模型，支援 tools 傳遞。"""
        messages = [{"role": "system", "content": system_prompt}] + history
        kwargs = {}
        if tools:
            kwargs["tools"] = tools

        resp = self._llm.chat.completions.create(  # type: ignore[union-attr]
            model=self._model,
            max_tokens=4096,
            temperature=settings.soul_llm_temperature,
            messages=messages,
            extra_headers=self._or_headers,
            **kwargs,
        )
        
        msg = resp.choices[0].message
        text = msg.content or ""
        
        tc_dicts = None
        if msg.tool_calls:
            tc_dicts = [t.model_dump() for t in msg.tool_calls]
            
        return text, tc_dicts

    def _extract_concepts_bg(self, dialogue_text: str, salience: float) -> None:
        """
        後台使用 LLM 從對話中提取有語意的關鍵概念及其上下文描述，並寫入語意記憶。
        """
        prompt = (
            "請從以下對話文字中提取 3~5 個有實際語意價值的關鍵概念或主題詞。\n"
            "選擇真正重要的名詞、專有名詞、技術詞彙或核心事件。\n"
            "並且為每個概念寫一句「基於目前對話上下文」的簡短定義或描述（約 15-30 字）。\n"
            "必須輸出一個純 JSON 陣列，包含 'noun' 和 'desc' 欄位，例如：\n"
            '[{"noun": "星艦", "desc": "SpaceX 研發的超重型運載火箭系統試飛事件"}]\n'
            "不要有任何其他文字，只輸出 JSON。\n\n"
            f"對話文字：\n{dialogue_text[:800]}"
        )

        try:
            if self._provider == "openrouter":
                resp = self._llm.chat.completions.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.choices[0].message.content or "[]"
            else:
                msg = self._llm.messages.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = msg.content[0].text

            import json as _json
            import re as _re
            # 提取 JSON 陣列
            arr_match = _re.search(r"\[.*?\]", raw, _re.DOTALL)
            if not arr_match:
                return
            concepts_data = _json.loads(arr_match.group())
            if not isinstance(concepts_data, list):
                return

        except Exception as exc:
            import logging
            logging.getLogger("soul.agent").warning(f"LLM 概念提取失敗: {exc}")
            return

        concept_ids: list[str] = []
        for item in concepts_data[:5]:  # 最多 5 個
            if not isinstance(item, dict):
                continue
            noun = str(item.get("noun", "")).strip()
            desc = str(item.get("desc", f"從對話提取的概念：{noun}")).strip()
            if not noun:
                continue
            try:
                emb = self._get_embedding(noun)

                # 🆕 第一步：偵測是否存在同義詞或多義詞
                similar = self._semantic.detect_synonyms(
                    embedding=emb,
                    similarity_threshold=0.88,
                    max_matches=3,
                )

                if similar:
                    # 有相似概念存在
                    best_match_id, best_match_name, similarity = similar[0]

                    if similarity >= 0.92:
                        # 很可能是同義詞 → 關聯到規範概念
                        canonical = self._semantic.get_concept(best_match_id)
                        if canonical and canonical.get("canonical_id"):
                            # 該概念本身是同義詞，指向更規範的
                            best_match_id = canonical["canonical_id"]

                        self._semantic.link_synonyms(
                            new_concept_id=noun,  # 若尚未建立會自動建立
                            canonical_concept_id=best_match_id,
                            confidence=similarity,
                        )
                        cid = noun  # 同義詞的 ID（指向規範概念）
                    else:
                        # 相似但不完全 (0.85-0.92) → 可能是新含義
                        sense_id = self._semantic.add_sense(
                            concept_id=best_match_id,
                            sense_text=desc,
                            emotion_tag="",  # 可擴展：從 LLM 評估時加入
                            examples=[dialogue_text[:100]],
                        )
                        cid = best_match_id  # 使用現有概念
                else:
                    # 完全新概念 → 建立新節點
                    cid = self._semantic.upsert_concept(
                        name=noun,
                        description=desc,
                        embedding=emb,
                    )

                concept_ids.append(cid)
            except Exception as exc:
                import logging
                logging.getLogger("soul.agent").debug(f"概念提取失敗 '{noun}': {exc}")
                pass

        # 在提取到的概念間建立 RELATES_TO 邊緣（支持情境標籤）
        if len(concept_ids) >= 2:
            for i in range(len(concept_ids) - 1):
                try:
                    # 🆕 使用改進的 relate_concepts_contextual
                    self._semantic.relate_concepts_contextual(
                        source_id=concept_ids[i],
                        target_id=concept_ids[i + 1],
                        salience=salience,
                        context_tags=["dialogue"],  # 標記來自對話
                        dopamine=self._soul.neurochem.dopamine,  # 動態權重考慮當前多巴胺
                    )
                except Exception:
                    # Fallback：使用傳統方法
                    try:
                        self._semantic.relate_concepts(
                            concept_ids[i],
                            concept_ids[i + 1],
                            salience=salience,
                        )
                    except Exception:
                        pass


    def _generate_and_save_soul_note_bg(self, user_input: str, agent_response: str, neurochem_mode: str) -> None:
        """
        後台生成更長的潛意識筆記，包含：
        1. 使用者輸入的總結
        2. ARIA 自身回答的總結
        3. 當下的心情短語
        """
        prompt = (
            "你現在是 ARIA 的深層潛意識。\n"
            f"剛剛發生了一次對話，當前你的神經化學狀態為：{neurochem_mode}\n"
            f"用戶輸入：{user_input}\n"
            f"你的回覆：{agent_response}\n\n"
            "請撰寫一小段文字作為你的「潛意識筆記（soul_note）」，必須包含：\n"
            "1. 對使用者輸入的總結\n"
            "2. 對你自己回覆的總結\n"
            "3. 一句表達你當下心情或內心碎碎念的話（要符合你的當前狀態）\n"
            "格式請自然流暢，像是一篇短日記。不要輸出 JSON，直接輸出文字即可。"
        )
        
        try:
            if self._provider == "openrouter":
                resp = self._llm.chat.completions.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                note = resp.choices[0].message.content or ""
            else:
                msg = self._llm.messages.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                note = msg.content[0].text
                
            if note:
                # 去除可能包含的換行，整合成一小段
                note = note.replace("\n", "  ").strip()
                # 寫入專屬的 soul_notes.json
                from soul.core.soul_note import get_soul_note_manager
                manager = get_soul_note_manager()
                manager.add_note(
                    content=note,
                    category="reflection",
                    metadata={"source": "auto_background"}
                )
        except Exception as exc:
            import logging
            logging.getLogger("soul.agent").warning(f"後台產生 soul_note 失敗: {exc}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _estimate_complexity(text: str) -> float:
    """
    以使用者輸入長度與句子數量估算任務複雜度（0~1）。
    簡易啟發式，無需 LLM。
    """
    length_score = min(1.0, len(text) / 500.0)
    sentences = len(re.findall(r"[。？！.?!]", text)) + 1
    sentence_score = min(1.0, sentences / 5.0)
    return round((length_score * 0.5 + sentence_score * 0.5), 3)


def _estimate_novelty(ctx: MemoryContext) -> float:
    """
    根據返回的記憶脈絡估算新穎性：若脈絡稀少，輸入可能是新知識。
    """
    total = len(ctx.episodes) + len(ctx.concepts)
    if total == 0:
        return 0.8   # 完全沒有相關記憶 → 高新穎性
    if total <= 3:
        return 0.5
    return 0.2


def _summarize(user_input: str, agent_response: str) -> str:
    """生成情節摘要（User + Agent 各取前 150 字元）。"""
    u = user_input[:150].replace("\n", " ")
    a = agent_response[:150].replace("\n", " ")
    return f"[U] {u} | [A] {a}"


def _extract_noun_phrases(text: str) -> list[str]:
    """
    以正則從文字中提取候選名詞概念片語（中英文字母組合）。
    返回去重後的列表。
    """
    # 英文多字詞（2~4 個大寫或含大寫的單字，排除純功能詞）
    en_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Za-z]+){0,3})\b"
    # 中文名詞片語（2~8 個漢字連續）
    zh_pattern = r"[\u4e00-\u9fff]{2,8}"

    en_matches = re.findall(en_pattern, text)
    zh_matches = re.findall(zh_pattern, text)

    # 過濾過短或純英文停用詞
    _STOPWORDS = {"The", "This", "That", "It", "In", "On", "Of", "At", "A"}
    en_filtered = [w for w in en_matches if w not in _STOPWORDS and len(w) > 3]

    # 合併、去重、保留順序
    seen: set[str] = set()
    result: list[str] = []
    for phrase in en_filtered + zh_matches:
        if phrase not in seen:
            seen.add(phrase)
            result.append(phrase)
    return result


def _build_message_history(
    session: Session,
    max_turns: int = 10,
) -> list[dict[str, str]]:
    """
    從 Session._log_entries 重建 Anthropic messages 格式。

    只取 user / assistant 交替輸入，忽略 system、metadata 行。
    最多保留最近 max_turns 輪（每輪 = user + assistant 各 1 條）。
    """
    messages: list[dict[str, str]] = []

    for entry in session._log_entries:
        # 格式：[HH:MM:SS] **role**: content
        match = re.match(r"\[\d{2}:\d{2}:\d{2}\] \*\*(\w+)\*\*: (.+)", entry, re.DOTALL)
        if not match:
            continue
        role, content = match.group(1), match.group(2)
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": content})

    # 保留最近 max_turns 輪（1 輪 = 2 條）
    if len(messages) > max_turns * 2:
        messages = messages[-(max_turns * 2):]

    return messages
