"""
soul/memory/episodic.py

情節記憶圖譜：儲存對話歷史、事件、記憶痕跡（Engrams）。
對應大腦分區：海馬迴 — 情節記憶編碼與時序組織
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from soul.memory.graph import GraphClient, compute_edge_weight, new_id, now_iso
from soul.core.config import settings


class EpisodicMemory:
    """
    情節記憶管理器。

    節點類型：
      - Episode：對話事件（記憶痕跡 Engram）
      - Entity：情節中提取的具體實體

    邊類型：
      - PRECEDES：時序連結
      - MENTIONS：Episode → Entity
      - TRIGGERED_BY：觸發回憶的線索鏈
    """

    def __init__(self, client: GraphClient) -> None:
        self._graph = client.episodic

    # ── Episode CRUD ──────────────────────────────────────────────────────────

    def write_episode(
        self,
        user_input: str,
        agent_response: str,
        session_id: str,
        content_summary: str,
        embedding: list[float] | None = None,
        da_weight: float = 0.5,
        ht_weight: float = 0.5,
        salience_score: float = 0.5,
    ) -> str:
        """
        寫入新的情節記憶節點（Engram）。

        Args:
            user_input: 使用者原始輸入
            agent_response: Agent 回覆內容
            session_id: 當前 Session ID
            content_summary: 對話摘要（用於圖譜搜尋）
            embedding: 內容向量嵌入
            da_weight: 虛擬多巴胺強度（記憶烙印深度）
            ht_weight: 虛擬血清素強度（穩定性標記）
            salience_score: 情感顯著性分數

        Returns:
            新建的 Episode ID
        """
        eid = new_id()
        emb_str = _vec_str(embedding) if embedding else _vec_str([0.0] * settings.soul_embedding_dim)

        self._graph.query(
            f"""
            CREATE (e:Episode {{
                id: $id,
                content: $content,
                user_input: $user_input,
                agent_response: $response,
                embedding: vecf32({emb_str}),
                timestamp: $ts,
                session_id: $session,
                da_weight: $da,
                ht_weight: $ht,
                salience_score: $sal,
                is_dreamed: false
            }})
            """,
            params={
                "id": eid,
                "content": content_summary,
                "user_input": user_input,
                "response": agent_response,
                "ts": now_iso(),
                "session": session_id,
                "da": da_weight,
                "ht": ht_weight,
                "sal": salience_score,
            },
        )

        # 連結到同一 Session 的前一個 Episode（時序鏈）
        self._link_to_previous(eid, session_id)

        return eid

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        result = self._graph.ro_query(
            "MATCH (e:Episode {id: $id}) RETURN e LIMIT 1",
            params={"id": episode_id},
        ).result_set
        if not result:
            return None
        return dict(result[0][0].properties)

    def get_session_episodes(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """取得某個 Session 的所有情節，按時序排序。"""
        result = self._graph.ro_query(
            """
            MATCH (e:Episode {session_id: $sid})
            RETURN e ORDER BY e.timestamp ASC LIMIT $limit
            """,
            params={"sid": session_id, "limit": limit},
        ).result_set
        return [dict(row[0].properties) for row in result]

    def mark_dreamed(self, episode_id: str) -> None:
        """標記情節為已在夢境中重播過。"""
        self._graph.query(
            "MATCH (e:Episode {id: $id}) SET e.is_dreamed = true",
            params={"id": episode_id},
        )

    # ── Entity CRUD ───────────────────────────────────────────────────────────

    def write_entity(
        self,
        name: str,
        entity_type: str,
        description: str,
        episode_id: str,
    ) -> str:
        """
        寫入從情節中提取的實體（Engram Entity）。
        entity_type: "person" | "concept" | "action" | "tool"
        """
        # 先找是否已存在同名 Entity
        result = self._graph.ro_query(
            "MATCH (n:Entity {name: $name}) RETURN n.id LIMIT 1",
            params={"name": name},
        ).result_set

        if result:
            nid = result[0][0]
        else:
            nid = new_id()
            self._graph.query(
                """
                CREATE (n:Entity {
                    id: $id,
                    name: $name,
                    type: $type,
                    description: $desc,
                    src: $src
                })
                """,
                params={
                    "id": nid,
                    "name": name,
                    "type": entity_type,
                    "desc": description,
                    "src": episode_id,
                },
            )

        # Episode -[MENTIONS]-> Entity
        self._graph.query(
            """
            MATCH (e:Episode {id: $eid}), (n:Entity {id: $nid})
            MERGE (e)-[:MENTIONS]->(n)
            """,
            params={"eid": episode_id, "nid": nid},
        )
        return nid

    # ── High-Salience Episodes（Dream Engine 用）─────────────────────────────

    def get_high_salience_undreamed(
        self,
        da_threshold: float | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        取得高多巴胺且尚未重播的情節，供 LiDER Dream Engine 使用。
        """
        threshold = da_threshold or settings.soul_dream_replay_da_threshold
        result = self._graph.ro_query(
            """
            MATCH (e:Episode)
            WHERE e.da_weight >= $threshold AND e.is_dreamed = false
            RETURN e ORDER BY e.da_weight DESC, e.salience_score DESC
            LIMIT $limit
            """,
            params={"threshold": threshold, "limit": limit},
        ).result_set
        return [dict(row[0].properties) for row in result]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        nodes = self._graph.ro_query("MATCH (n) RETURN count(n) AS cnt").result_set
        edges = self._graph.ro_query("MATCH ()-[r]->() RETURN count(r) AS cnt").result_set
        episodes = self._graph.ro_query(
            "MATCH (e:Episode) RETURN count(e) AS cnt"
        ).result_set
        undreamed = self._graph.ro_query(
            "MATCH (e:Episode {is_dreamed: false}) RETURN count(e) AS cnt"
        ).result_set
        return {
            "nodes": nodes[0][0] if nodes else 0,
            "edges": edges[0][0] if edges else 0,
            "episodes": episodes[0][0] if episodes else 0,
            "undreamed": undreamed[0][0] if undreamed else 0,
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _link_to_previous(self, new_episode_id: str, session_id: str) -> None:
        """將新情節連結到同 Session 最近一個情節，建立 PRECEDES 邊緣。"""
        result = self._graph.ro_query(
            """
            MATCH (e:Episode {session_id: $sid})
            WHERE e.id <> $eid
            RETURN e.id AS id ORDER BY e.timestamp DESC LIMIT 1
            """,
            params={"sid": session_id, "eid": new_episode_id},
        ).result_set

        if result:
            prev_id = result[0][0]
            self._graph.query(
                """
                MATCH (prev:Episode {id: $prev}), (curr:Episode {id: $curr})
                CREATE (prev)-[:PRECEDES {time_delta: 0}]->(curr)
                """,
                params={"prev": prev_id, "curr": new_episode_id},
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vec_str(embedding: list[float]) -> str:
    return "[" + ", ".join(str(x) for x in embedding) + "]"
