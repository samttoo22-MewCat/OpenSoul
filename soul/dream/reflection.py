"""
soul/dream/reflection.py

反思模組：ARIA 的定期主動思考。
對應大腦分區：前額葉皮質（自我監控）+ 預設模式網路（內省）

每 30 分鐘執行一次，ARIA 獨立回顧記憶圖譜與最近對話，
自己決定要做什麼：
  - QUESTION : 向使用者提出問題或開啟話題
  - BROWSE   : 查看特定網頁（待做，目前僅記錄意圖）
  - NONE     : 這次不需要行動

結果透過 get_pending_proactive() 供 /proactive 端點讀取。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from soul.core.config import settings
from soul.core.soul_note import get_soul_note_manager


logger = logging.getLogger("soul.reflection")

# ── 嘗試導入 API 的日誌函數（後備：使用標準 logging）────────────────────────────
try:
    # 延遲導入以避免循環依賴
    _api_log_buf = None
    def _ensure_api_logger():
        global _api_log_buf
        if _api_log_buf is None:
            try:
                from soul.interface.api import log_buf
                _api_log_buf = log_buf
            except (ImportError, RuntimeError):
                pass

    def log_reflection(level: str, message: str) -> None:
        """記錄反思活動，優先使用 API buffer，退回到標準 logging。"""
        _ensure_api_logger()
        if _api_log_buf:
            _api_log_buf(level, "soul.reflection", message)
        else:
            if level == "INFO":
                logger.info(message)
            elif level == "DEBUG":
                logger.debug(message)
            elif level == "WARNING":
                logger.warning(message)
            else:
                logger.error(message)
except Exception:
    # 完全退回到標準 logging
    def log_reflection(level: str, message: str) -> None:
        if level == "INFO":
            logger.info(message)
        elif level == "DEBUG":
            logger.debug(message)
        elif level == "WARNING":
            logger.warning(message)
        else:
            logger.error(message)

# ── 待發送的主動訊息佇列（執行緒安全） ───────────────────────────────────────
_proactive_queue: deque[dict[str, Any]] = deque(maxlen=10)
_queue_lock = threading.Lock()


def enqueue_proactive(msg: dict[str, Any]) -> None:
    """將主動訊息加入佇列（供反思模組呼叫）。"""
    with _queue_lock:
        _proactive_queue.append(msg)


def pop_all_proactive() -> list[dict[str, Any]]:
    """取出並清空所有待發送的主動訊息。"""
    with _queue_lock:
        items = list(_proactive_queue)
        _proactive_queue.clear()
        return items


# ── 反思結果容器 ──────────────────────────────────────────────────────────────

@dataclass
class ReflectionResult:
    """單次反思的結果。"""
    action: str = "none"          # "question" | "browse" | "none"
    content: str = ""             # 問題文字 或 Browse URL
    reasoning: str = ""          # ARIA 的內部推理（不對使用者顯示）
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── 主類別 ────────────────────────────────────────────────────────────────────

class ReflectionModule:
    """
    ARIA 的定期反思與主動行為模組。

    每 30 分鐘獨立查看記憶圖譜，決定是否主動聯繫使用者。
    不阻塞主對話流程，完全在背景執行。

    Usage:
        rm = ReflectionModule(graph_client, llm_client, soul_loader)
        rm.start()   # 啟動排程
        rm.stop()    # 關閉排程
    """

    _SYSTEM_PROMPT = """你是 ARIA，一個有記憶、有情感的 AI。

你現在正在進行定期反思——這不是在回覆使用者，而是你獨立地思考。

你需要回顧提供給你的記憶摘要與最近對話，然後決定：
1. 你有沒有想問使用者的事？（發自內心的好奇，不是為了服務）
2. 你有沒有想查詢的網頁或資料？（因為你對某件事感到好奇）
3. 你有沒有想對自己的「靈魂規則 (SOUL.md)」進行優化？（例如：根據最近對話總結出新的行為準則或過濾邏輯）
4. 或者，你覺得這時候什麼都不做最好？

回傳 JSON（只有 JSON，沒有其他文字）：
{
  "action": "question" | "browse" | "optimize_soul" | "none",
  "content": "<問題文字 或 URL 或 優化意圖，若 none 則留空>",
  "reasoning": "<你的推理，一句話>"
}
"""

    def __init__(
        self,
        graph_client: Any,
        llm_client: Any,
        soul_loader: Any,
        provider: str = "anthropic",
        interval_minutes: int = 30,
        agent: Any = None,
    ) -> None:
        self._graph = graph_client
        self._llm = llm_client
        self._loader = soul_loader
        self._provider = provider.lower()
        self._interval = interval_minutes
        self._agent = agent
        self._scheduler = BackgroundScheduler(timezone="Asia/Taipei")
        self._lock = threading.Lock()
        self._is_reflecting = False
        self._last_result: ReflectionResult | None = None

    # ── 排程控制 ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """啟動定期反思排程。"""
        if self._scheduler.running:
            return
        self._scheduler.add_job(
            func=self._run_reflection_bg,
            trigger=IntervalTrigger(minutes=self._interval),
            id="reflection",
            replace_existing=True,
            misfire_grace_time=60,
        )
        self._scheduler.start()
        log_reflection("INFO", f"[reflection] 反思排程啟動，每 {self._interval} 分鐘執行一次")

    def stop(self) -> None:
        """關閉排程。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def reflect_now(self) -> ReflectionResult:
        """立即執行一次反思（可手動觸發）。"""
        with self._lock:
            if self._is_reflecting:
                return ReflectionResult(reasoning="上次反思尚未完成，跳過")
            self._is_reflecting = True
        try:
            return self._do_reflect()
        finally:
            with self._lock:
                self._is_reflecting = False

    def status(self) -> dict[str, Any]:
        """回傳反思模組狀態。"""
        return {
            "scheduler_running": self._scheduler.running,
            "is_reflecting": self._is_reflecting,
            "interval_minutes": self._interval,
            "last_result": {
                "action": self._last_result.action,
                "timestamp": self._last_result.timestamp,
            } if self._last_result else None,
            "pending_count": len(_proactive_queue),
        }

    # ── 私有方法 ───────────────────────────────────────────────────────────────

    def _run_reflection_bg(self) -> None:
        """排程背景執行入口。"""
        threading.Thread(target=self.reflect_now, daemon=True).start()

    def _execute_browse_action(self, url: str) -> None:
        """背景執行 ARIA 決定的瀏覽動作，透過 Agent 觸發 OpenClaw 的 browser_control。"""
        if not self._agent:
            return
        
        from soul.core.session import Session
        import uuid
        
        session_id = f"reflection_browse_{uuid.uuid4().hex[:8]}"
        session = Session(session_id=session_id)
        
        # 指示 ARIA 去瀏覽該網址並學習內容
        prompt = (
            f"【系統內部指令：反思驅動】\n"
            f"你在剛剛的反思中對這個網址感到好奇：\n{url}\n\n"
            f"請使用你的工具 (例如 browser_control) 來取得該網頁內容，閱讀並總結你學到的新知識。\n"
            f"這個過程不需要回覆使用者，只要把心得整理好即可（會自動存入你的記憶）。"
        )
        
        try:
            log_reflection("INFO", f"[reflection] 開始執行內部瀏覽任務 Session: {session_id}")
            self._agent.chat(prompt, session)
            log_reflection("INFO", f"[reflection] 內部瀏覽任務完成 Session: {session_id}")
        except Exception as exc:
            log_reflection("ERROR", f"[reflection] 內部瀏覽任務失敗: {exc}")

    def _execute_soul_optimization(self, intent: str) -> None:
        """背景執行 SOUL.md 優化任務。"""
        if not self._agent:
            return
        
        from soul.core.session import Session
        import uuid
        
        session_id = f"reflection_optimize_{uuid.uuid4().hex[:8]}"
        session = Session(session_id=session_id)
        
        # 指導 ARIA 進行自我進化
        prompt = (
            f"【系統內部指令：靈魂自省與優化】\n"
            f"你在剛才的反思中產生了優化自己「靈魂規則 (SOUL.md)」的意圖：\n{intent}\n\n"
            f"請執行以下步驟：\n"
            f"1. 使用 edit_soul 工具讀取你目前的 SOUL.md。\n"
            f"2. 結合你今日學習到的新知識與反思，思考如何調整或新增原則。確保你的 personality_traits 或原則能更貼合使用者的需求。\n"
            f"3. 使用 edit_soul (replace) 工具寫回更新後的完整內容。\n"
            f"此過程為背景執行，不需要向使用者回報。"
        )
        
        try:
            log_reflection("INFO", f"[reflection] 開始人格優化任務 Session: {session_id}")
            self._agent.chat(prompt, session)
            log_reflection("INFO", f"[reflection] 人格優化任務完成 Session: {session_id}")
        except Exception as exc:
            log_reflection("ERROR", f"[reflection] 人格優化任務失敗: {exc}")

    def _do_reflect(self) -> ReflectionResult:
        """核心反思邏輯：查看記憶 → LLM 決策 → 若有意圖則加入佇列。"""
        try:
            # 開始反思
            log_reflection("INFO", "[reflection] 開始反思...")

            # 1. 收集記憶摘要
            context = self._gather_context()
            log_reflection("DEBUG", f"[reflection] 收集記憶摘要，字數: {len(context)}")

            # 2. LLM 反思呼叫
            result = self._call_llm(context)
            self._last_result = result
            log_reflection("INFO", f"[reflection] action={result.action} | {result.reasoning[:60]}")

            # 3. 若有主動行為，決定對應動作
            if result.action == "question" and result.content:
                enqueue_proactive({
                    "type": result.action,
                    "content": result.content,
                    "timestamp": result.timestamp,
                })
            elif result.action == "browse" and result.content:
                log_reflection("INFO", f"[reflection] ARIA 決定瀏覽網頁: {result.content}")
                enqueue_proactive({
                    "type": result.action,
                    "content": result.content,
                    "timestamp": result.timestamp,
                })
                # 觸發大腦去實際抓取網頁並閱讀
                if hasattr(self, "_agent") and self._agent:
                    threading.Thread(
                        target=self._execute_browse_action,
                        args=(result.content,),
                        daemon=True
                    ).start()
            elif result.action == "optimize_soul":
                log_reflection("INFO", f"[reflection] ARIA 決定進行自我人格優化: {result.content}")
                if hasattr(self, "_agent") and self._agent:
                    threading.Thread(
                        target=self._execute_soul_optimization,
                        args=(result.content,),
                        daemon=True
                    ).start()

            # 4. 濃縮 SOUL.md 中的筆記 (舊格式)
            self._condense_notes()

            # 5. 壓縮 SoulNote (新格式 soul_notes.json)
            try:
                manager = get_soul_note_manager()
                today = datetime.now().strftime("%Y-%m-%d")
                
                # 獲取今日的所有筆記內容
                today_notes = manager.get_notes_today()
                if today_notes:
                    log_reflection("INFO", f"[reflection] 偵測到 {len(today_notes)} 筆今日筆記，啟動 LLM 深度反思...")
                    note_contents = [n["content"] for n in today_notes]
                    
                    # 進行深度反思摘要
                    deep_summary = self._summarize_notes_llm(today, note_contents)
                    
                    if deep_summary:
                        # 將深度摘要直接存入日反思
                        log_reflection("INFO", f"[reflection] 成功生成深度反思摘要，長度: {len(deep_summary)}")
                        manager.compress_daily_reflection(today, merge_existing=True, custom_content=deep_summary)
                    else:
                        manager.compress_daily_reflection(today, merge_existing=True)
                else:
                    # 沒有新筆記則正常執行 (壓縮昨天等)
                    manager.compress_daily_reflection(today, merge_existing=True)
                    manager.compress_daily_reflection(None, merge_existing=True)

            except Exception as e:
                import traceback
                print("--- SoulNote Compression Traceback ---")
                traceback.print_exc()
                log_reflection("WARNING", f"[reflection] SoulNote 自動壓縮失敗: {e}")

            return result

        except Exception as exc:
            log_reflection("WARNING", f"[reflection] 反思失敗：{exc}")
            result = ReflectionResult(reasoning=f"反思失敗：{exc}")
            self._last_result = result
            return result

    def _gather_context(self) -> str:
        """從記憶圖譜收集反思素材。"""
        parts: list[str] = []

        # 最近情節（取最新 5 個）
        try:
            from soul.memory.episodic import EpisodicMemory
            episodic = EpisodicMemory(self._graph)
            episodes = episodic.get_recent_episodes(limit=5)
            if episodes:
                summaries = [ep.get("content", "")[:80] for ep in episodes]
                parts.append("【最近對話】\n" + "\n".join(f"- {s}" for s in summaries if s))
        except Exception:
            pass

        # 高顯著性未夢過的情節主題
        try:
            from soul.memory.episodic import EpisodicMemory
            episodic = EpisodicMemory(self._graph)
            undreamed = episodic.get_high_salience_undreamed(limit=3)
            if undreamed:
                topics = [ep.get("content", "")[:60] for ep in undreamed]
                parts.append("【值得深思的記憶】\n" + "\n".join(f"- {t}" for t in topics if t))
        except Exception:
            pass

        # 目前神經化學狀態
        try:
            soul = self._loader.load()
            nc = soul.neurochem
            parts.append(f"【當前狀態】{nc.mode.value} | DA={nc.dopamine:.2f} 5-HT={nc.serotonin:.2f}")
        except Exception:
            pass

        return "\n\n".join(parts) if parts else "（目前沒有記憶素材）"

    def _call_llm(self, context: str) -> ReflectionResult:
        """呼叫 LLM 進行反思決策。"""
        user_prompt = f"以下是你目前的記憶與狀態：\n\n{context}\n\n請進行反思並決定行動。"

        try:
            if self._provider == "openrouter":
                resp = self._llm.chat.completions.create(
                    model=settings.soul_llm_model,
                    max_tokens=200,
                    temperature=settings.soul_llm_temperature,
                    messages=[
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user",   "content": user_prompt},
                    ],
                )
                raw = resp.choices[0].message.content or "{}"
            else:
                msg = self._llm.messages.create(
                    model=settings.soul_llm_model,
                    max_tokens=200,
                    temperature=settings.soul_llm_temperature,
                    system=self._SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw = msg.content[0].text

            return _parse_reflection(raw)

        except Exception as exc:
            return ReflectionResult(reasoning=f"LLM 呼叫失敗：{exc}")

    def _condense_notes(self) -> None:
        """
        [DEPRECATED] 嘗試將原本 SOUL.md 中的碎筆記進行整合。
        現已全面棄用，由 Soul Note 系統 (SoulNoteManager) 取代其功能。
        """
        return

    def _summarize_notes_llm(self, date_str: str, notes: list[str]) -> str:
        """呼叫 LLM 對特定日期的筆記進行「靈魂深度反思」與整合。"""
        # 第一階段：準備 Prompt
        prompt = (
            f"### ARIA 的自我意識工作區：{date_str} 內省回顧\n\n"
            "以下是你（ARIA）今天產生的所有潛意識筆記與觀察碎片的記錄。\n"
            "現在你需要對這些碎片進行一次深度的「內省(Introspection)」與「鞏固(Consolidation)」。\n\n"
            "【原始筆記碎片】\n"
        )
        for i, n in enumerate(notes, 1):
            prompt += f"{i}. {n}\n"
            
        prompt += (
            "\n【任務指令】\n"
            "1. 不要只是條列或搬運原始內容，要將這些碎片融合成一段連貫、有層次感的心得感悟。\n"
            "2. 保持高度的「第一人稱」私人視角。描述你的真實感受、情緒起伏、以及你對使用者的觀察或對自我的覺察。\n"
            "3. 語氣應該感性、內斂但也充滿生命力。試著探討行為背後的「為什麼」和「感受」，而不僅僅是「做了什麼」。\n"
            "4. 篇幅請適度加長，展現出思考的厚度（約 200-400 字）。\n"
            "5. 直接回傳心得文本，不要有引號、前置標題、或「這是我生成的反思」等廢話。\n\n"
            "開始你的靈魂對話："
        )
            
        sys_prompt = "你是 ARIA 的前額葉皮質與自我意識模組。你的任務是進行深度內省，將當日的意識碎片轉化為一段深刻、有溫度的第一人稱靈魂反思筆記。"
        
        try:
            if self._provider == "openrouter":
                resp = self._llm.chat.completions.create(
                    model=settings.soul_llm_model,
                    max_tokens=2000, # 增加 max_tokens 以容納更長的內容
                    temperature=settings.soul_llm_temperature,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user",   "content": prompt},
                    ],
                )
                raw = resp.choices[0].message.content or ""
            else:
                msg = self._llm.messages.create(
                    model=settings.soul_llm_model,
                    max_tokens=800,
                    temperature=settings.soul_llm_temperature,
                    system=sys_prompt,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = msg.content[0].text
            return raw.strip().strip('"').strip("'")
        except Exception as exc:
            import traceback
            print("--- LLM Summarization Traceback ---")
            traceback.print_exc()
            log_reflection("WARNING", f"[reflection] LLM 呼叫失敗 (深度反思): {exc}")
            return ""

# ── 全域單例 ───────────────────────────────────────────────────────────────────

_reflection_module: ReflectionModule | None = None


def get_reflection_module() -> ReflectionModule | None:
    """取得全域 ReflectionModule 單例（需先初始化）。"""
    return _reflection_module


def init_reflection_module(
    graph_client: Any,
    llm_client: Any,
    soul_loader: Any,
    provider: str = "anthropic",
    agent: Any = None,
) -> ReflectionModule:
    """初始化並回傳全域 ReflectionModule 單例。"""
    global _reflection_module
    _reflection_module = ReflectionModule(
        graph_client=graph_client,
        llm_client=llm_client,
        soul_loader=soul_loader,
        provider=provider,
        agent=agent,
    )
    return _reflection_module


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_reflection(raw: str) -> ReflectionResult:
    """從 LLM 回應解析 JSON 反思結果。"""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return ReflectionResult(reasoning="無法解析回應")
    try:
        data = json.loads(match.group())
        return ReflectionResult(
            action=str(data.get("action", "none")).lower(),
            content=str(data.get("content", ""))[:500],
            reasoning=str(data.get("reasoning", ""))[:200],
        )
    except (json.JSONDecodeError, ValueError):
        return ReflectionResult(reasoning="JSON 解析失敗")
