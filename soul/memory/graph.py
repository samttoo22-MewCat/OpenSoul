"""
soul/memory/graph.py

FalkorDB 連線管理、三圖譜初始化、向量索引建立、動態邊緣權重計算。
對應大腦分區：海馬迴 (Hippocampus) — 記憶編碼與拓撲結構維護
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from falkordb import FalkorDB, Graph

from soul.core.config import settings


class GraphClient:
    """FalkorDB 連線管理器，提供三個記憶圖譜的存取介面。"""

    def __init__(self) -> None:
        kwargs: dict[str, Any] = {
            "host": settings.falkordb_host,
            "port": settings.falkordb_port,
        }
        pw = settings.falkordb_password.strip()
        if pw:
            kwargs["password"] = pw

        self._client = FalkorDB(**kwargs)
        self._semantic: Graph | None = None
        self._episodic: Graph | None = None
        self._procedural: Graph | None = None

    @property
    def semantic(self) -> Graph:
        if self._semantic is None:
            self._semantic = self._client.select_graph(settings.soul_semantic_graph)
        return self._semantic

    @property
    def episodic(self) -> Graph:
        if self._episodic is None:
            self._episodic = self._client.select_graph(settings.soul_episodic_graph)
        return self._episodic

    @property
    def procedural(self) -> Graph:
        if self._procedural is None:
            self._procedural = self._client.select_graph(settings.soul_procedural_graph)
        return self._procedural

    def ping(self) -> bool:
        """確認 FalkorDB 連線是否正常。"""
        try:
            self._client.connection.ping()
            return True
        except Exception:
            return False

    def clear_all(self) -> dict[str, int]:
        """清除三個記憶圖譜的所有節點與邊。回傳各圖譜刪除節點數。"""
        results = {}
        for name, graph in [
            ("semantic",   self.semantic),
            ("episodic",   self.episodic),
            ("procedural", self.procedural),
        ]:
            try:
                r = graph.query("MATCH (n) DETACH DELETE n")
                results[name] = r.nodes_deleted or 0
            except Exception:
                results[name] = 0
        return results


def initialize_schemas(client: GraphClient) -> None:
    """
    建立三個記憶圖譜的 Schema 與向量索引。
    冪等操作：若索引已存在則跳過。
    """
    _init_semantic(client.semantic)
    _init_episodic(client.episodic)
    _init_procedural(client.procedural)


# ── Semantic Memory Schema ────────────────────────────────────────────────────

def _init_semantic(graph: Graph) -> None:
    """初始化語意記憶圖譜：Concept、Rule 節點 + 向量索引。"""
    # 建立向量索引（Concept.embedding）
    _safe_query(graph, f"""
        CREATE VECTOR INDEX FOR (c:Concept) ON (c.embedding)
        OPTIONS {{dimension: {settings.soul_embedding_dim}, similarityFunction: 'cosine'}}
    """)

    # 建立一般索引加速 Cypher 查詢
    _safe_query(graph, "CREATE INDEX FOR (c:Concept) ON (c.id)")
    _safe_query(graph, "CREATE INDEX FOR (c:Concept) ON (c.name)")
    _safe_query(graph, "CREATE INDEX FOR (r:Rule) ON (r.id)")
    _safe_query(graph, "CREATE INDEX FOR (r:Rule) ON (r.domain)")


# ── Episodic Memory Schema ────────────────────────────────────────────────────

def _init_episodic(graph: Graph) -> None:
    """初始化情節記憶圖譜：Episode、Entity 節點 + 向量索引。"""
    _safe_query(graph, f"""
        CREATE VECTOR INDEX FOR (e:Episode) ON (e.embedding)
        OPTIONS {{dimension: {settings.soul_embedding_dim}, similarityFunction: 'cosine'}}
    """)

    _safe_query(graph, "CREATE INDEX FOR (e:Episode) ON (e.id)")
    _safe_query(graph, "CREATE INDEX FOR (e:Episode) ON (e.session_id)")
    _safe_query(graph, "CREATE INDEX FOR (e:Episode) ON (e.is_dreamed)")
    _safe_query(graph, "CREATE INDEX FOR (e:Episode) ON (e.da_weight)")
    _safe_query(graph, "CREATE INDEX FOR (n:Entity) ON (n.id)")
    _safe_query(graph, "CREATE INDEX FOR (n:Entity) ON (n.name)")


# ── Procedural Memory Schema ──────────────────────────────────────────────────

def _init_procedural(graph: Graph) -> None:
    """初始化程序性記憶圖譜：Procedure 節點 + 向量索引。"""
    _safe_query(graph, f"""
        CREATE VECTOR INDEX FOR (p:Procedure) ON (p.embedding)
        OPTIONS {{dimension: {settings.soul_embedding_dim}, similarityFunction: 'cosine'}}
    """)

    _safe_query(graph, "CREATE INDEX FOR (p:Procedure) ON (p.id)")
    _safe_query(graph, "CREATE INDEX FOR (p:Procedure) ON (p.domain)")
    _safe_query(graph, "CREATE INDEX FOR (p:Procedure) ON (p.success_count)")


# ── Dynamic Edge Weight ───────────────────────────────────────────────────────

def compute_edge_weight(
    last_accessed: datetime,
    frequency: int,
    salience: float,
    max_frequency: int = 100,
    alpha: float | None = None,
    beta: float | None = None,
    gamma: float | None = None,
    decay_lambda: float | None = None,
) -> float:
    """
    動態邊緣權重計算。

    W(u,v) = α·Recency(t) + β·Frequency(n) + γ·Salience

    - Recency(t)   = exp(-λ·t)               指數衰減
    - Frequency(n) = log(1+n) / log(1+n_max) 赫布學習（對數正規化）
    - Salience     = clamp(salience, 0, 1)   情感顯著性（由杏仁核提供）
    """
    α = alpha if alpha is not None else settings.soul_weight_alpha
    β = beta if beta is not None else settings.soul_weight_beta
    γ = gamma if gamma is not None else settings.soul_weight_gamma
    λ = decay_lambda if decay_lambda is not None else settings.soul_decay_lambda

    elapsed_hours = (datetime.now(UTC) - last_accessed).total_seconds() / 3600.0
    recency = math.exp(-λ * elapsed_hours)

    max_freq = max(max_frequency, 1)
    freq_score = math.log1p(frequency) / math.log1p(max_freq)

    sal = max(0.0, min(1.0, salience))

    return α * recency + β * freq_score + γ * sal


def new_id() -> str:
    """生成新的 UUID 字串，用於所有節點 ID。"""
    return str(uuid.uuid4())


def now_iso() -> str:
    """返回目前 UTC 時間的 ISO 格式字串。"""
    return datetime.now(UTC).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_query(graph: Graph, query: str) -> None:
    """執行 Cypher 查詢，忽略「已存在」類的錯誤（冪等保護）。"""
    try:
        graph.query(query)
    except Exception as e:
        err = str(e).lower()
        # 索引已存在是正常情況，忽略
        if any(k in err for k in ("already exists", "equivalent index", "already indexed")):
            return
        raise


# 全域單例
_graph_client: GraphClient | None = None


def get_graph_client() -> GraphClient:
    """取得全域 GraphClient 單例（Lazy 初始化）。"""
    global _graph_client
    if _graph_client is None:
        _graph_client = GraphClient()
    return _graph_client


def _vec_str(embedding: list[float]) -> str:
    """將 float 列表轉為 FalkorDB vecf32() 語法用的字串。"""
    return "[" + ", ".join(str(x) for x in embedding) + "]"
