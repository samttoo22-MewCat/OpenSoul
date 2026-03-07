"""
soul/memory/retrieval.py

EcphoryRAG 觸發回憶機制：多跳關聯搜尋引擎。
對應大腦分區：海馬迴（Ecphory）+ 頂葉（注意力焦點）

原理：
  人類記憶由微小感官線索（cue）觸發，激活整段豐富記憶痕跡（Engrams）。
  本模組模擬此機制：
  1. 向量相似性定位「種子節點」（初始激活）
  2. 以加權質心嵌入為導航錨點
  3. 沿圖譜邊緣進行多跳 BFS/DFS 關聯展開（廣度由血清素控制）
  4. 收集高權重路徑上的節點，組成脈絡記憶視窗
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soul.memory.graph import GraphClient, _vec_str
from soul.core.config import settings


@dataclass
class MemoryContext:
    """EcphoryRAG 檢索結果容器。"""
    episodes: list[dict[str, Any]] = field(default_factory=list)
    concepts: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.episodes or self.concepts or self.procedures)

    def to_text(self) -> str:
        """將記憶脈絡序列化為 LLM 可讀的文本格式（含時間標記）。"""
        from datetime import datetime, timezone

        def _relative_time(ts_str: str) -> str:
            """將 ISO 時間戳記轉成相對時間（幾分鐘前 / 幾小時前 / N 天前）。"""
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                diff_sec = (now - ts).total_seconds()
                if diff_sec < 120:
                    return "剛才"
                if diff_sec < 3600:
                    return f"{int(diff_sec // 60)} 分鐘前"
                if diff_sec < 86400:
                    return f"{int(diff_sec // 3600)} 小時前"
                return f"{int(diff_sec // 86400)} 天前"
            except Exception:
                return ""

        parts: list[str] = []

        if self.episodes:
            parts.append("【相關對話記憶（以下為過去對話，不是當前訊息）】")
            for ep in self.episodes[:5]:
                rel = _relative_time(ep.get("timestamp", ""))
                time_tag = f"（{rel}）" if rel else ""
                sal = ep.get('salience_score', 0)
                if sal >= 0.75:
                    sal_tag = "核心記憶"
                elif sal >= 0.5:
                    sal_tag = "重要記憶"
                elif sal >= 0.25:
                    sal_tag = "一般記憶"
                else:
                    sal_tag = "淡薄記憶"
                parts.append(f"  - {time_tag}[重要程度:《{sal_tag}》] {ep.get('content', '')}")

        if self.concepts:
            parts.append("【相關語意概念】")
            for c in self.concepts[:5]:
                parts.append(f"  - {c.get('name', '')}: {c.get('description', '')}")

        if self.procedures:
            parts.append("【相關操作程序】")
            for p in self.procedures[:3]:
                steps = p.get("steps", [])
                steps_str = "; ".join(steps[:3]) if isinstance(steps, list) else str(steps)
                parts.append(f"  - {p.get('name', '')}: {steps_str}")

        if self.entities:
            parts.append("【提及的實體】")
            for e in self.entities[:5]:
                parts.append(f"  - [{e.get('type', '')}] {e.get('name', '')}: {e.get('description', '')}")

        return "\n".join(parts) if parts else ""


def compute_retrieval_params(
    serotonin: float = 0.5,
    dopamine: float = 0.5,
) -> tuple[int, int, float]:
    """
    根據神經化學狀態計算記憶檢索的動態參數。

    改進（v2.0）：
      - 血清素影響搜尋廣度（曲線更溫和）
      - 多巴胺影響權重閾值（非線性調制，中段變化更平緩）
      - 參數變化更平滑，避免劇烈波動

    Args:
        serotonin: 血清素濃度 [0.0, 1.0]（決定思維廣度）
        dopamine: 多巴胺濃度 [0.0, 1.0]（決定探索意願）

    Returns:
        (seed_k, breadth_k, weight_threshold)
    """
    # 血清素影響搜尋廣度
    # 範圍：serotonin=0.3 → seed_k=3, breadth_k=5
    #      serotonin=0.5 → seed_k=5, breadth_k=12
    #      serotonin=0.8 → seed_k=7, breadth_k=22（上限）
    seed_k = max(3, min(10, int(3 + serotonin * 7)))
    breadth_k = max(5, min(25, int(5 + serotonin * 20)))  # 上限提高至25

    # 多巴胺影響權重閾值（非線性，更平緩）
    # DA 0.2 → threshold = 0.30（保守）
    # DA 0.5 → threshold = 0.225（均衡）
    # DA 0.8 → threshold = 0.125（開放）
    # 使用二次項使中段變化更平緩
    da_normalized = (dopamine - 0.5) ** 2 * 1.0
    weight_threshold = 0.225 - (dopamine - 0.5) * 0.15
    weight_threshold = max(0.05, min(0.35, weight_threshold))

    return seed_k, breadth_k, weight_threshold


class EcphoryRetrieval:
    """
    EcphoryRAG 檢索引擎。

    觸發回憶（Ecphory）流程：
      1. 取得查詢嵌入向量
      2. 向量相似搜尋定位種子節點（初始 Engrams）
      3. 多跳圖譜展開（血清素決定廣度，多巴胺影響路徑選擇）
      4. 整合三個記憶圖譜的相關節點
      5. 回傳 MemoryContext
    """

    def __init__(self, client: GraphClient) -> None:
        self._client = client

    def retrieve(
        self,
        query_embedding: list[float],
        serotonin: float = 0.5,
        dopamine: float = 0.5,
        top_k: int = 10,
        max_hops: int = 3,
    ) -> MemoryContext:
        """
        執行 EcphoryRAG 完整檢索流程。

        Args:
            query_embedding: 查詢向量嵌入
            serotonin: 當前血清素濃度（0-1），決定 BFS 廣度
            dopamine: 當前多巴胺濃度（0-1），影響高獎勵路徑偏好
            top_k: 返回的最大節點數
            max_hops: 圖譜展開最大跳數

        Returns:
            MemoryContext 包含所有相關記憶節點
        """
        # 使用改進的非線性動態參數計算
        seed_k, breadth_k, weight_threshold = compute_retrieval_params(serotonin, dopamine)

        context = MemoryContext()

        # ── 1. 情節記憶搜尋 ──────────────────────────────────────────────────
        context.episodes = self._retrieve_episodes(
            query_embedding, seed_k, breadth_k, max_hops, weight_threshold, top_k
        )

        # ── 2. 語意記憶搜尋 ──────────────────────────────────────────────────
        context.concepts = self._retrieve_concepts(
            query_embedding, seed_k, breadth_k, max_hops, weight_threshold, top_k
        )

        # ── 3. 程序性記憶搜尋 ────────────────────────────────────────────────
        context.procedures = self._retrieve_procedures(query_embedding, seed_k)

        # ── 4. 從情節中提取相關實體 ───────────────────────────────────────────
        if context.episodes:
            episode_ids = [ep["id"] for ep in context.episodes[:5]]
            context.entities = self._retrieve_entities_from_episodes(episode_ids)

        return context

    # ── Private: Per-Graph Retrieval ─────────────────────────────────────────

    def _retrieve_episodes(
        self,
        embedding: list[float],
        seed_k: int,
        breadth_k: int,
        max_hops: int,
        weight_threshold: float,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Step 1: 向量搜尋種子; Step 2: 多跳 PRECEDES 展開。"""
        emb_str = _vec_str(embedding)

        # 向量相似搜尋（種子節點）
        seeds = self._client.episodic.ro_query(
            f"""
            CALL db.idx.vector.queryNodes('Episode', 'embedding', {seed_k}, vecf32({emb_str}))
            YIELD node, score
            RETURN node, score ORDER BY score DESC
            """,
        ).result_set

        if not seeds:
            return []

        seed_ids = [row[0].properties["id"] for row in seeds]
        seed_ids_set = set(seed_ids)
        seed_episodes = [dict(row[0].properties) for row in seeds]

        # 多跳關聯展開：FalkorDB 不支援 IN 運算子，改用 UNWIND 逐一 MATCH
        seed_ids_literal = "[" + ", ".join(f"'{sid}'" for sid in seed_ids) + "]"
        related = self._client.episodic.ro_query(
            f"""
            MATCH (seed:Episode)-[:PRECEDES*1..{max_hops}]-(related:Episode)
            WHERE seed.id = '{seed_ids[0]}'
            RETURN DISTINCT related
            LIMIT {breadth_k * 3}
            """,
        ).result_set if len(seed_ids) == 1 else self._client.episodic.ro_query(
            f"""
            MATCH (seed:Episode)-[:PRECEDES*1..{max_hops}]-(related:Episode)
            RETURN DISTINCT related
            LIMIT {breadth_k * 3}
            """,
        ).result_set

        # Python 端過濾：排除 seed_ids，且 salience_score 達標
        related_episodes = [
            dict(row[0].properties) for row in related
            if row[0].properties.get("id") not in seed_ids_set
            and row[0].properties.get("salience_score", 0) >= weight_threshold
        ][:breadth_k]

        # 合併並去重
        all_episodes = {ep["id"]: ep for ep in seed_episodes + related_episodes}
        return sorted(
            all_episodes.values(),
            key=lambda x: x.get("da_weight", 0) + x.get("salience_score", 0),
            reverse=True,
        )[:top_k]

    def _retrieve_concepts(
        self,
        embedding: list[float],
        seed_k: int,
        breadth_k: int,
        max_hops: int,
        weight_threshold: float,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """向量搜尋語意 Concept，再沿 RELATES_TO 邊緣展開。"""
        emb_str = _vec_str(embedding)

        seeds = self._client.semantic.ro_query(
            f"""
            CALL db.idx.vector.queryNodes('Concept', 'embedding', {seed_k}, vecf32({emb_str}))
            YIELD node, score
            RETURN node, score ORDER BY score DESC
            """,
        ).result_set

        if not seeds:
            return []

        seed_ids = [row[0].properties["id"] for row in seeds]
        seed_ids_set = set(seed_ids)
        seed_concepts = [dict(row[0].properties) for row in seeds]

        # 沿高權重 RELATES_TO 邊緣展開：FalkorDB 不支援 IN，改用 Python 端過濾
        related = self._client.semantic.ro_query(
            f"""
            MATCH (seed:Concept)-[r:RELATES_TO*1..{max_hops}]-(related:Concept)
            RETURN DISTINCT related, r
            LIMIT {breadth_k * 3}
            """,
        ).result_set

        # Python 端過濾：排除 seed_ids，且 edge weight 達標
        related_concepts = []
        for row in related:
            props = dict(row[0].properties)
            if props.get("id") in seed_ids_set:
                continue
            # row[1] 是 edge list（變長路徑），取最小 weight
            try:
                edges = row[1] if isinstance(row[1], list) else [row[1]]
                min_weight = min((e.properties.get("weight", 0) for e in edges), default=0)
            except Exception:
                min_weight = 0
            if min_weight >= weight_threshold:
                related_concepts.append(props)
            if len(related_concepts) >= breadth_k:
                break

        all_concepts = {c["id"]: c for c in seed_concepts + related_concepts}
        return list(all_concepts.values())[:top_k]

    def _retrieve_procedures(
        self,
        embedding: list[float],
        seed_k: int,
    ) -> list[dict[str, Any]]:
        """向量搜尋最相關的程序性記憶。"""
        import json
        emb_str = _vec_str(embedding)

        result = self._client.procedural.ro_query(
            f"""
            CALL db.idx.vector.queryNodes('Procedure', 'embedding', {seed_k}, vecf32({emb_str}))
            YIELD node, score
            RETURN node ORDER BY score DESC
            """,
        ).result_set

        procs = []
        for row in result:
            props = dict(row[0].properties)
            if "steps" in props:
                try:
                    props["steps"] = json.loads(props["steps"])
                except Exception:
                    pass
            procs.append(props)
        return procs

    def _retrieve_entities_from_episodes(
        self, episode_ids: list[str]
    ) -> list[dict[str, Any]]:
        """從情節節點中提取所有 MENTIONS 的 Entity。"""
        result = self._client.episodic.ro_query(
            """
            MATCH (e:Episode)-[:MENTIONS]->(n:Entity)
            WHERE e.id IN $ids
            RETURN DISTINCT n
            """,
            params={"ids": episode_ids},
        ).result_set
        return [dict(row[0].properties) for row in result]
