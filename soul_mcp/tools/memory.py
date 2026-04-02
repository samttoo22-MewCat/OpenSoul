"""
soul_mcp/tools/memory.py

MCP Tool: soul_memory_retrieve
從 OpenSoul 圖譜記憶中檢索相關情節、概念、程序。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("soul_mcp.memory")


def soul_memory_retrieve(query: str, top_k: int = 5) -> dict[str, Any]:
    """
    從 OpenSoul 圖譜記憶中檢索與 query 最相關的情節、概念、程序。
    使用 EcphoryRAG 聯想記憶引擎（向量搜尋 + 多跳 BFS 展開）。

    需要 FalkorDB 連線（docker-compose up -d）。

    Args:
        query: 搜尋查詢文字
        top_k: 每類記憶最多回傳筆數（1-20）

    Returns:
        {
          "episodes":   [{id, content, timestamp, salience_score}, ...],
          "concepts":   [{id, name, description}, ...],
          "procedures": [{id, name, steps}, ...],
          "entities":   [{id, name, type, description}, ...],
          "backend":    "falkordb"
        }
    """
    top_k = max(1, min(20, top_k))

    # ── 1. 取得 embedding ──────────────────────────────────────────────────
    try:
        from soul.core.agent import EmbeddingService
        emb_svc = EmbeddingService()
        embedding = emb_svc.embed(query)
    except Exception as e:
        logger.warning(f"[soul_memory_retrieve] Embedding 失敗：{e}")
        return _empty_result("embedding_failed")

    # ── 2. 取得神經化學狀態（影響搜尋廣度）──────────────────────────────
    try:
        from soul_mcp.adapters.neurochem_adapter import load_neurochem
        neuro = load_neurochem()
        serotonin = neuro.serotonin
        dopamine = neuro.dopamine
    except Exception:
        serotonin, dopamine = 0.5, 0.5

    # ── 3. 連線 FalkorDB ──────────────────────────────────────────────────
    try:
        from soul.memory.graph import get_graph_client
        client = get_graph_client()
        if not client.ping():
            raise ConnectionError("FalkorDB ping 失敗")
    except Exception as e:
        logger.error(f"[soul_memory_retrieve] FalkorDB 無法連線：{e}")
        return {
            "results": [],
            "episodes": [], "concepts": [], "procedures": [], "entities": [],
            "error": f"FalkorDB 無法連線：{e}",
            "hint": "請執行 docker-compose up -d",
        }

    # ── 4. EcphoryRAG 檢索 ────────────────────────────────────────────────
    try:
        from soul.memory.retrieval import EcphoryRetrieval
        retrieval = EcphoryRetrieval(client)
        ctx = retrieval.retrieve(
            query_embedding=embedding,
            serotonin=serotonin,
            dopamine=dopamine,
            top_k=top_k,
        )
    except Exception as e:
        logger.error(f"[soul_memory_retrieve] 檢索失敗：{e}")
        return _empty_result(f"retrieval_error: {e}")

    # ── 5. 序列化結果 ─────────────────────────────────────────────────────
    def _clean(node: dict, keys: list[str]) -> dict:
        return {k: node.get(k) for k in keys if node.get(k) is not None}

    return {
        "episodes": [
            _clean(ep, ["id", "content", "user_input", "agent_response",
                        "timestamp", "session_id", "salience_score", "da_weight"])
            for ep in ctx.episodes
        ],
        "concepts": [
            _clean(c, ["id", "name", "description", "type"])
            for c in ctx.concepts
        ],
        "procedures": [
            _clean(p, ["id", "name", "steps", "domain", "success_count"])
            for p in ctx.procedures
        ],
        "entities": [
            _clean(e, ["id", "name", "type", "description"])
            for e in ctx.entities
        ],
        "backend": "falkordb",
        "query": query,
    }


def _empty_result(reason: str) -> dict[str, Any]:
    return {
        "episodes": [],
        "concepts": [],
        "procedures": [],
        "entities": [],
        "backend": "unavailable",
        "error": reason,
    }
