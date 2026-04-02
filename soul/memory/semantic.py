"""
soul/memory/semantic.py

語意記憶圖譜：儲存概念、事實、抽象規則。
對應大腦分區：海馬迴 + 新皮質 — 長期語意知識網路
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from soul.memory.graph import GraphClient, compute_edge_weight, new_id, now_iso
from soul.core.config import settings


class SemanticMemory:
    """
    語意記憶管理器。

    節點類型：
      - Concept：概念節點（實體、規則、抽象）
      - Rule：邏輯規則節點

    邊類型：
      - RELATES_TO：概念間關聯（含動態權重）
      - HAS_RULE：概念 → 規則
      - CONTRADICTS：矛盾標記
      - LATENT_BRIDGE：Dream Engine 建立的潛意識捷徑
    """

    def __init__(self, client: GraphClient) -> None:
        self._graph = client.semantic

    # ── Concept CRUD ──────────────────────────────────────────────────────────

    def upsert_concept(
        self,
        name: str,
        description: str,
        concept_type: str = "entity",
        embedding: list[float] | None = None,
    ) -> str:
        """
        插入或更新 Concept 節點。若 name 已存在則更新描述與時間戳。
        使用 MERGE 避免並發競態產生重複節點。回傳 concept ID。
        """
        new_cid = new_id()
        emb_str = _vec_str(embedding) if embedding else _vec_str([0.0] * settings.soul_embedding_dim)
        now_str = now_iso()

        result = self._graph.query(
            f"""
            MERGE (c:Concept {{name: $name}})
            ON CREATE SET
                c.id             = $id,
                c.type           = $type,
                c.description    = $desc,
                c.embedding      = vecf32({emb_str}),
                c.canonical_id   = null,
                c.polysemy_dict  = '{{}}',
                c.synonyms       = [],
                c.created_at     = $now,
                c.updated_at     = $now,
                c.last_sense_discovered = $now
            ON MATCH SET
                c.description    = $desc,
                c.type           = $type,
                c.updated_at     = $now
            RETURN c.id AS id
            """,
            params={
                "id": new_cid,
                "name": name,
                "type": concept_type,
                "desc": description,
                "now": now_str,
            },
        ).result_set

        if result:
            return result[0][0]
        return new_cid

    def get_concept(self, concept_id: str) -> dict[str, Any] | None:
        result = self._graph.ro_query(
            "MATCH (c:Concept {id: $id}) RETURN c",
            params={"id": concept_id},
        ).result_set
        if not result:
            return None
        return dict(result[0][0].properties)

    def find_concept_by_name(self, name: str) -> dict[str, Any] | None:
        result = self._graph.ro_query(
            "MATCH (c:Concept {name: $name}) RETURN c LIMIT 1",
            params={"name": name},
        ).result_set
        if not result:
            return None
        return dict(result[0][0].properties)

    def update_embedding(self, concept_id: str, embedding: list[float]) -> None:
        emb_str = _vec_str(embedding)
        self._graph.query(
            f"MATCH (c:Concept {{id: $id}}) SET c.embedding = vecf32({emb_str})",
            params={"id": concept_id},
        )

    # ── Rule CRUD ─────────────────────────────────────────────────────────────

    def upsert_rule(
        self,
        condition: str,
        action: str,
        domain: str,
        confidence: float = 0.8,
    ) -> str:
        result = self._graph.ro_query(
            "MATCH (r:Rule {condition: $cond, domain: $domain}) RETURN r.id LIMIT 1",
            params={"cond": condition, "domain": domain},
        ).result_set

        if result:
            rid = result[0][0]
            self._graph.query(
                "MATCH (r:Rule {id: $id}) SET r.confidence = $conf, r.action = $action",
                params={"id": rid, "conf": confidence, "action": action},
            )
            return rid

        rid = new_id()
        self._graph.query(
            """
            CREATE (r:Rule {
                id: $id,
                condition: $cond,
                action: $action,
                confidence: $conf,
                domain: $domain
            })
            """,
            params={
                "id": rid,
                "cond": condition,
                "action": action,
                "conf": confidence,
                "domain": domain,
            },
        )
        return rid

    # ── Edge Management ───────────────────────────────────────────────────────

    def relate_concepts(
        self,
        source_id: str,
        target_id: str,
        salience: float = 0.5,
    ) -> None:
        """
        建立或更新兩個 Concept 之間的 RELATES_TO 邊緣。
        若已存在則增加 frequency 並重新計算 weight。
        """
        now = datetime.utcnow()
        now_str = now.isoformat()

        existing = self._graph.ro_query(
            """
            MATCH (u:Concept {id: $uid})-[r:RELATES_TO]->(v:Concept {id: $vid})
            RETURN r.frequency AS freq, r.last_accessed AS la
            LIMIT 1
            """,
            params={"uid": source_id, "vid": target_id},
        ).result_set

        if existing:
            freq = (existing[0][0] or 0) + 1
            la_str = existing[0][1] or now_str
            try:
                last_accessed = datetime.fromisoformat(la_str)
            except Exception:
                last_accessed = now

            weight = compute_edge_weight(
                last_accessed=last_accessed,
                frequency=freq,
                salience=salience,
            )
            self._graph.query(
                """
                MATCH (u:Concept {id: $uid})-[r:RELATES_TO]->(v:Concept {id: $vid})
                SET r.weight = $w, r.frequency = $freq,
                    r.recency = $rec, r.salience = $sal,
                    r.last_accessed = $now
                """,
                params={
                    "uid": source_id,
                    "vid": target_id,
                    "w": weight,
                    "freq": freq,
                    "rec": compute_edge_weight(last_accessed, 0, 0.0),
                    "sal": salience,
                    "now": now_str,
                },
            )
        else:
            weight = compute_edge_weight(
                last_accessed=now,
                frequency=1,
                salience=salience,
            )
            self._graph.query(
                """
                MATCH (u:Concept {id: $uid}), (v:Concept {id: $vid})
                CREATE (u)-[:RELATES_TO {
                    weight: $w,
                    frequency: 1,
                    recency: $rec,
                    salience: $sal,
                    last_accessed: $now
                }]->(v)
                """,
                params={
                    "uid": source_id,
                    "vid": target_id,
                    "w": weight,
                    "rec": 1.0,
                    "sal": salience,
                    "now": now_str,
                },
            )

    def relate_concepts_contextual(
        self,
        source_id: str,
        target_id: str,
        salience: float = 0.5,
        context_tags: list[str] | None = None,
        dopamine: float = 0.5,
    ) -> None:
        """
        創建或更新概念關聯，支持情境標籤和動態權重。

        改進功能：
          - 支持情境標籤（如 ["財務", "決策"]）
          - 跟蹤 co-occurrence（同時出現次數）
          - 計算動態權重（考慮當前多巴胺）

        Args:
            source_id, target_id: 概念ID
            salience: 顯著性 [0.0, 1.0]
            context_tags: 情境標籤列表
            dopamine: 當前多巴胺水平（用於動態權重計算）
        """
        now = datetime.utcnow()
        now_str = now.isoformat()

        # 查詢現有邊
        existing = self._graph.ro_query(
            """
            MATCH (u:Concept {id: $uid})-[r:RELATES_TO]->(v:Concept {id: $vid})
            RETURN r.frequency AS freq, r.last_accessed AS la,
                   r.co_occurrence_count AS cooc, r.context_tags AS tags
            LIMIT 1
            """,
            params={"uid": source_id, "vid": target_id},
        ).result_set

        if existing:
            # 更新現有邊
            freq = (existing[0][0] or 0) + 1
            cooc = (existing[0][2] or 0) + 1
            old_tags = existing[0][3] or []
            new_tags = list(set((old_tags or []) + (context_tags or [])))

            weight = compute_edge_weight(
                last_accessed=datetime.fromisoformat(existing[0][1]),
                frequency=freq,
                salience=salience,
            )

            # 計算動態權重（多巴胺越高，邊越易激活）
            dynamic_weight = weight * (1.0 - dopamine * 0.1)

            self._graph.query(
                """
                MATCH (u:Concept {id: $uid})-[r:RELATES_TO]->(v:Concept {id: $vid})
                SET r.frequency = $freq,
                    r.weight = $w,
                    r.dynamic_weight = $dw,
                    r.last_accessed = $now,
                    r.co_occurrence_count = $cooc,
                    r.context_tags = $tags,
                    r.da_modulation = $da_mod
                """,
                params={
                    "uid": source_id,
                    "vid": target_id,
                    "freq": freq,
                    "w": weight,
                    "dw": dynamic_weight,
                    "now": now_str,
                    "cooc": cooc,
                    "tags": new_tags,
                    "da_mod": 1.0 - dopamine * 0.1,
                },
            )
        else:
            # 創建新邊
            weight = compute_edge_weight(now, 1, salience)
            dynamic_weight = weight * (1.0 - dopamine * 0.1)

            self._graph.query(
                """
                MATCH (u:Concept {id: $uid}), (v:Concept {id: $vid})
                CREATE (u)-[r:RELATES_TO {
                    frequency: 1,
                    weight: $w,
                    dynamic_weight: $dw,
                    recency: 1.0,
                    salience: $sal,
                    last_accessed: $now,
                    co_occurrence_count: 1,
                    context_tags: $tags,
                    da_modulation: $da_mod,
                    last_neuro_update: $now
                }]->(v)
                """,
                params={
                    "uid": source_id,
                    "vid": target_id,
                    "w": weight,
                    "dw": dynamic_weight,
                    "sal": salience,
                    "now": now_str,
                    "tags": context_tags or [],
                    "da_mod": 1.0 - dopamine * 0.1,
                },
            )

    def add_latent_bridge(self, source_id: str, target_id: str, reason: str = "") -> None:
        """Dream Engine 建立的跨域潛意識捷徑。"""
        self._graph.query(
            """
            MATCH (u:Concept {id: $uid}), (v:Concept {id: $vid})
            MERGE (u)-[r:LATENT_BRIDGE]->(v)
            SET r.reason = $reason, r.created_at = $now
            """,
            params={"uid": source_id, "vid": target_id, "reason": reason, "now": now_iso()},
        )

    def mark_contradiction(self, source_id: str, target_id: str) -> None:
        self._graph.query(
            """
            MATCH (u:Concept {id: $uid}), (v:Concept {id: $vid})
            MERGE (u)-[:CONTRADICTS]->(v)
            """,
            params={"uid": source_id, "vid": target_id},
        )

    # ── Polysemy & Synonyms ───────────────────────────────────────────────────

    def detect_synonyms(
        self,
        embedding: list[float],
        similarity_threshold: float = 0.85,
        max_matches: int = 5,
    ) -> list[tuple[str, str, float]]:
        """
        向量搜索找出可能的同義詞（相似度 >= threshold）。

        Args:
            embedding: 新概念的向量
            similarity_threshold: 同義字閾值（0.85-0.95）
            max_matches: 最多返回N個候選

        Returns:
            [(candidate_id, name, similarity_score), ...]
        """
        emb_str = _vec_str(embedding)
        result = self._graph.ro_query(f"""
            CALL db.idx.vector.queryNodes('Concept', 'embedding', {max_matches}, vecf32({emb_str}))
            YIELD node, score
            WHERE score >= {similarity_threshold}
            RETURN node.id, node.name, score
            ORDER BY score DESC
        """).result_set

        return [(r[0], r[1], r[2]) for r in result]

    def link_synonyms(
        self,
        new_concept_id: str,
        canonical_concept_id: str,
        confidence: float = 0.85,
    ) -> None:
        """
        將新概念標記為現有概念的同義詞。

        Args:
            new_concept_id: 新發現的概念ID
            canonical_concept_id: 指向的規範概念ID
            confidence: 同義度置信度
        """
        self._graph.query(
            """
            MATCH (new:Concept {id: $new_id}), (canonical:Concept {id: $canon_id})
            SET new.canonical_id = $canon_id
            CREATE (new)-[:SYNONYM_OF {
                confidence: $conf,
                created_at: $now,
                reason: "向量相似度"
            }]->(canonical)
            """,
            params={
                "new_id": new_concept_id,
                "canon_id": canonical_concept_id,
                "conf": confidence,
                "now": now_iso(),
            },
        )

        # 同步更新規範概念的 synonyms 列表
        new_concept = self.get_concept(new_concept_id)
        if new_concept:
            self._graph.query(
                "MATCH (c:Concept {id: $id}) SET c.synonyms = c.synonyms + [$syn]",
                params={"id": canonical_concept_id, "syn": new_concept.get("name")},
            )

    def add_sense(
        self,
        concept_id: str,
        sense_text: str,
        emotion_tag: str = "",
        examples: list[str] | None = None,
    ) -> str:
        """
        為現有概念添加新含義。

        Args:
            concept_id: 目標概念ID
            sense_text: 新含義的文字描述
            emotion_tag: 情感標籤（可選）
            examples: 使用示例列表

        Returns:
            新含義的 sense_id
        """
        concept = self.get_concept(concept_id)
        if not concept:
            raise ValueError(f"Concept {concept_id} not found")

        sense_id = new_id()
        polysemy_dict = json.loads(concept.get("polysemy_dict", "{}")) or {}

        polysemy_dict[sense_id] = {
            "text": sense_text,
            "emotion_tag": emotion_tag,
            "examples": examples or [],
            "salience": 0.5,  # 新含義初始顯著性
            "first_seen": now_iso(),
            "episodes": [],
            "usage_count": 0,
        }

        self._graph.query(
            """
            MATCH (c:Concept {id: $id})
            SET c.polysemy_dict = $polysemy,
                c.last_sense_discovered = $now
            """,
            params={
                "id": concept_id,
                "polysemy": json.dumps(polysemy_dict),
                "now": now_iso(),
            },
        )

        return sense_id

    def update_sense_salience(
        self,
        concept_id: str,
        sense_id: str,
        salience_delta: float,
    ) -> None:
        """
        更新含義的顯著性（遞增式）。

        Args:
            concept_id: 概念ID
            sense_id: 含義ID
            salience_delta: 顯著性變化量（-0.2 到 +0.2）
        """
        concept = self.get_concept(concept_id)
        if not concept:
            raise ValueError(f"Concept {concept_id} not found")

        polysemy_dict = json.loads(concept.get("polysemy_dict", "{}")) or {}

        if sense_id not in polysemy_dict:
            raise ValueError(f"Sense {sense_id} not found")

        # 累積更新並鉗制到 [0, 1]
        current_salience = polysemy_dict[sense_id].get("salience", 0.5)
        new_salience = max(0.0, min(1.0, current_salience + salience_delta))
        polysemy_dict[sense_id]["salience"] = new_salience

        self._graph.query(
            "MATCH (c:Concept {id: $id}) SET c.polysemy_dict = $polysemy",
            params={
                "id": concept_id,
                "polysemy": json.dumps(polysemy_dict),
            },
        )

    def get_primary_sense(self, concept_id: str) -> dict[str, Any]:
        """獲取概念的主要含義（顯著性最高的）。"""
        concept = self.get_concept(concept_id)
        if not concept:
            return {"sense_id": None, "text": "", "salience": 0.0}

        polysemy_dict = json.loads(concept.get("polysemy_dict", "{}")) or {}

        if not polysemy_dict:
            return {
                "sense_id": None,
                "text": concept.get("description", ""),
                "salience": 1.0,
            }

        primary = max(polysemy_dict.items(), key=lambda x: x[1].get("salience", 0))
        return {
            "sense_id": primary[0],
            "text": primary[1].get("text"),
            "salience": primary[1].get("salience"),
            "emotion_tag": primary[1].get("emotion_tag"),
        }

    def get_canonical_concept(self, concept_id: str) -> str | None:
        """
        若該概念是同義詞，返回規範概念ID。
        否則返回 None。
        """
        concept = self.get_concept(concept_id)
        if not concept:
            return None
        return concept.get("canonical_id")

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        nodes = self._graph.ro_query(
            "MATCH (n) RETURN count(n) AS cnt"
        ).result_set
        edges = self._graph.ro_query(
            "MATCH ()-[r]->() RETURN count(r) AS cnt"
        ).result_set
        return {
            "nodes": nodes[0][0] if nodes else 0,
            "edges": edges[0][0] if edges else 0,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vec_str(embedding: list[float]) -> str:
    """將 float 列表轉為 FalkorDB vecf32() 語法用的字串。"""
    return "[" + ", ".join(str(x) for x in embedding) + "]"
