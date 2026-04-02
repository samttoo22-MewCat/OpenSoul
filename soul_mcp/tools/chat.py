"""
soul_mcp/tools/chat.py

MCP Tool: soul_chat
與 OpenSoul 認知代理對話，觸發完整認知迴圈。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from soul.memory.graph import get_graph_client
from soul_mcp.adapters.graph_lite import get_lite_client
from soul.core.agent import SoulAgent
from soul.core.config import settings
from soul.core.session import Session

logger = logging.getLogger("soul_mcp.chat")



def soul_chat(message: str, session_id: str | None = None) -> dict[str, Any]:
    """
    與 OpenSoul 認知代理對話。
    觸發完整認知迴圈：記憶檢索 → 神經化學更新 → LLM 回覆 → 情節寫入。

    需要 FalkorDB 連線（docker-compose up -d）。

    Args:
        message:    使用者輸入訊息
        session_id: Session ID（留空自動建立）

    Returns:
        {
          "text":          LLM 回覆文字,
          "session_id":    Session ID,
          "episode_id":    情節記憶節點 ID,
          "gating_passed": 是否通過行為閘控,
          "gating_action": "pass" | "revise" | "suppress",
          "neurochem":     {dopamine, serotonin, mode, ...},
          "memory_hits":   {episodes, concepts, procedures},
          "backend":       "falkordb"
        }
    """
    if not message.strip():
        return {"error": "message 不可為空"}

    sid = session_id or str(uuid.uuid4())

    # ── 1. 連線 FalkorDB（若失敗則 fallback 到 SQLite lite client）─────────
    try:
        graph_client = get_graph_client()
        if not graph_client.ping():
            raise ConnectionError("FalkorDB ping 失敗")
    except Exception as falkor_err:
        logger.warning(f"[soul_chat] FalkorDB 無法連線（{falkor_err}），嘗試 lite client…")
        try:
            graph_client = get_lite_client()
        except Exception as lite_err:
            return {
                "error": f"FalkorDB 無法連線：{falkor_err}；lite client 也失敗：{lite_err}",
                "hint": "請執行 docker-compose up -d 啟動 FalkorDB",
                "session_id": sid,
            }

    # ── 2. 建立 SoulAgent ────────────────────────────────────────────────
    try:
        agent = SoulAgent(
            workspace=settings.workspace_path,
            graph_client=graph_client,
        )
    except Exception as e:
        logger.error(f"[soul_chat] SoulAgent 初始化失敗：{e}")
        return {"error": f"SoulAgent 初始化失敗：{e}"}

    # ── 3. 建立 Session ──────────────────────────────────────────────────
    try:
        session = Session(session_id=sid)
    except Exception as e:
        return {"error": f"Session 建立失敗：{e}"}

    # ── 4. 呼叫 SoulAgent.chat() ─────────────────────────────────────────
    try:
        resp = agent.chat(user_input=message, session=session)
    except Exception as e:
        logger.error(f"[soul_chat] agent.chat() 失敗：{e}")
        return {"error": f"對話失敗：{e}"}

    # ── 5. 組織回傳 ──────────────────────────────────────────────────────
    memory_hits = {
        "episodes": len(resp.memory_context.episodes),
        "concepts": len(resp.memory_context.concepts),
        "procedures": len(resp.memory_context.procedures),
    }

    return {
        "text": resp.text,
        "session_id": resp.session_id,
        "episode_id": resp.episode_id,
        "gating_passed": resp.gating_passed,
        "gating_action": resp.gating_action,
        "gating_score": round(resp.gating_score, 3),
        "neurochem": resp.neurochem,
        "memory_hits": memory_hits,
        "recommended_tool": resp.judge_decision.get("recommended_tool", "none"),
        "judge_reasoning": resp.judge_decision.get("reasoning", ""),
        "backend": "falkordb",
    }
