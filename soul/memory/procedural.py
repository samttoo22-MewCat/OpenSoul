"""
soul/memory/procedural.py

程序性記憶圖譜：儲存技能、SOP、成功的推理模式。
對應大腦分區：基底核（隱性技能）+ 小腦（程序自動化）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from soul.memory.graph import GraphClient, new_id, now_iso
from soul.core.config import settings


class ProceduralMemory:
    """
    程序性記憶管理器。

    節點類型：
      - Procedure：可執行的任務步驟序列

    邊類型：
      - REFINES：版本迭代歷史
      - APPLIES_TO：適用的語意概念範疇
      - DERIVED_FROM_EPISODE：來源情節
    """

    def __init__(self, client: GraphClient) -> None:
        self._graph = client.procedural

    # ── Procedure CRUD ────────────────────────────────────────────────────────

    def write_procedure(
        self,
        name: str,
        description: str,
        steps: list[str],
        domain: str,
        embedding: list[float] | None = None,
        source_episode_id: str | None = None,
    ) -> str:
        """
        寫入新的程序性記憶（技能）。

        Args:
            name: 程序名稱（如「資產負債表分析 SOP」）
            description: 程序描述
            steps: 步驟列表（JSON 序列化儲存）
            domain: 領域標籤（如 "finance", "coding", "analysis"）
            embedding: 向量嵌入
            source_episode_id: 此程序從哪個情節蒸餾而來

        Returns:
            新建的 Procedure ID
        """
        pid = new_id()
        steps_json = json.dumps(steps, ensure_ascii=False)
        emb_str = _vec_str(embedding) if embedding else _vec_str([0.0] * settings.soul_embedding_dim)

        self._graph.query(
            f"""
            CREATE (p:Procedure {{
                id: $id,
                name: $name,
                description: $desc,
                steps: $steps,
                embedding: vecf32({emb_str}),
                success_count: 0,
                failure_count: 0,
                domain: $domain,
                created_at: $now,
                last_used: $now
            }})
            """,
            params={
                "id": pid,
                "name": name,
                "desc": description,
                "steps": steps_json,
                "domain": domain,
                "now": now_iso(),
            },
        )

        if source_episode_id:
            self._graph.query(
                """
                MATCH (p:Procedure {id: $pid})
                MERGE (e_ref:EpisodeRef {id: $eid})
                CREATE (p)-[:DERIVED_FROM_EPISODE]->(e_ref)
                """,
                params={"pid": pid, "eid": source_episode_id},
            )

        return pid

    def refine_procedure(
        self,
        original_id: str,
        new_steps: list[str],
        new_description: str,
        embedding: list[float] | None = None,
    ) -> str:
        """
        從現有程序建立精化版本（LiDER Dream 後的更優路徑）。
        原始程序保留，新版本透過 REFINES 邊緣連結。
        """
        old = self.get_procedure(original_id)
        if not old:
            raise ValueError(f"Procedure {original_id} not found")

        new_pid = self.write_procedure(
            name=old["name"] + " (refined)",
            description=new_description,
            steps=new_steps,
            domain=old["domain"],
            embedding=embedding,
        )

        # 版本連結
        result = self._graph.ro_query(
            "MATCH (p:Procedure {id: $id})-[r:REFINES*]->(prev) RETURN count(r) AS v",
            params={"id": original_id},
        ).result_set
        version = (result[0][0] if result else 0) + 1

        self._graph.query(
            """
            MATCH (new:Procedure {id: $nid}), (old:Procedure {id: $oid})
            CREATE (new)-[:REFINES {version: $v}]->(old)
            """,
            params={"nid": new_pid, "oid": original_id, "v": version},
        )
        return new_pid

    def record_success(self, procedure_id: str) -> None:
        self._graph.query(
            """
            MATCH (p:Procedure {id: $id})
            SET p.success_count = p.success_count + 1,
                p.last_used = $now
            """,
            params={"id": procedure_id, "now": now_iso()},
        )

    def record_failure(self, procedure_id: str) -> None:
        self._graph.query(
            """
            MATCH (p:Procedure {id: $id})
            SET p.failure_count = p.failure_count + 1,
                p.last_used = $now
            """,
            params={"id": procedure_id, "now": now_iso()},
        )

    def get_procedure(self, procedure_id: str) -> dict[str, Any] | None:
        result = self._graph.ro_query(
            "MATCH (p:Procedure {id: $id}) RETURN p LIMIT 1",
            params={"id": procedure_id},
        ).result_set
        if not result:
            return None
        props = dict(result[0][0].properties)
        # 還原 steps JSON
        if "steps" in props:
            try:
                props["steps"] = json.loads(props["steps"])
            except Exception:
                pass
        return props

    def get_best_procedures(
        self, domain: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """取得成功率最高的程序（success_count 降序）。"""
        if domain:
            result = self._graph.ro_query(
                """
                MATCH (p:Procedure {domain: $domain})
                RETURN p ORDER BY p.success_count DESC LIMIT $limit
                """,
                params={"domain": domain, "limit": limit},
            ).result_set
        else:
            result = self._graph.ro_query(
                "MATCH (p:Procedure) RETURN p ORDER BY p.success_count DESC LIMIT $limit",
                params={"limit": limit},
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

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int | float]:
        nodes = self._graph.ro_query("MATCH (n) RETURN count(n) AS cnt").result_set
        edges = self._graph.ro_query("MATCH ()-[r]->() RETURN count(r) AS cnt").result_set
        total_success = self._graph.ro_query(
            "MATCH (p:Procedure) RETURN sum(p.success_count) AS s"
        ).result_set
        return {
            "nodes": nodes[0][0] if nodes else 0,
            "edges": edges[0][0] if edges else 0,
            "total_successes": total_success[0][0] if total_success else 0,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _vec_str(embedding: list[float]) -> str:
    return "[" + ", ".join(str(x) for x in embedding) + "]"
