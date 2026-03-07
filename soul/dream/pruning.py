"""
soul/dream/pruning.py

圖譜修剪與跨域橋接模組（頓悟機制）。
對應大腦分區：預設模式網路（DMN）— 突觸修剪與潛意識整合

兩大功能：
  1. 修剪（Pruning）：刪除低權重/過期邊緣，防止圖譜無限膨脹
  2. 橋接（Bridging）：找出語意相近但未連結的概念社群，
                       建立 LATENT_BRIDGE 捷徑（頓悟/靈光乍現機制）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soul.core.config import settings
from soul.memory.graph import GraphClient, _vec_str, now_iso


@dataclass
class PruningReport:
    """圖譜修剪週期的執行報告。"""
    edges_pruned: int = 0
    nodes_archived: int = 0
    bridges_created: int = 0
    max_frequency_updated: int = 0
    details: list[str] = field(default_factory=list)


class GraphPruning:
    """
    圖譜修剪器 + 跨域橋接器。

    修剪閾值（來自 settings）：
      - soul_prune_threshold（預設 0.05）：邊緣 weight 低於此值則刪除
      - salience < 0.1 且 30 天未存取 → 節點冷儲存標記

    橋接策略：
      - 在 soul_semantic 中找出向量距離接近但無直接連結的 Concept 對
      - 建立 LATENT_BRIDGE 邊緣

    Usage:
        pruner = GraphPruning(graph_client)
        report = pruner.run()
    """

    # 節點歸檔條件：多少天未存取
    _ARCHIVE_DAYS = 30
    # 橋接距離閾值（cosine 相似度）：大於此值才建立橋接
    _BRIDGE_SIMILARITY_THRESHOLD = 0.85
    # 每次最多建立多少條橋接邊緣
    _MAX_BRIDGES_PER_RUN = 10

    def __init__(self, client: GraphClient) -> None:
        self._client = client

    def run(self) -> PruningReport:
        """
        執行完整修剪 + 橋接週期。

        Returns:
            PruningReport 包含執行統計
        """
        report = PruningReport()

        self._prune_low_weight_edges(report)
        self._archive_stale_nodes(report)
        self._update_max_frequency(report)
        self._create_latent_bridges(report)

        return report

    # ── 1. 修剪低權重邊緣 ─────────────────────────────────────────────────────

    def _prune_low_weight_edges(self, report: PruningReport) -> None:
        """刪除 RELATES_TO 邊緣中 weight < prune_threshold 的邊緣。"""
        threshold = settings.soul_prune_threshold

        # 語意圖譜
        result_s = self._client.semantic.query(
            """
            MATCH (u:Concept)-[r:RELATES_TO]->(v:Concept)
            WHERE r.weight < $threshold
            DELETE r
            RETURN count(r) AS deleted
            """,
            params={"threshold": threshold},
        )
        s_count = _extract_count(result_s)

        # 情節圖譜（清理低顯著性的 PRECEDES 邊緣數量不做刪除，僅記錄）
        result_e = self._client.episodic.query(
            """
            MATCH (e:Episode)
            WHERE e.salience_score < $threshold AND e.is_dreamed = true
            RETURN count(e) AS cnt
            """,
            params={"threshold": threshold * 2},
        )
        e_count = _extract_count(result_e)

        total = s_count + e_count
        report.edges_pruned = total
        if total > 0:
            report.details.append(
                f"修剪邊緣：{s_count} 個語意邊緣，{e_count} 個低顯著性情節"
            )

    # ── 2. 歸檔過期節點 ───────────────────────────────────────────────────────

    def _archive_stale_nodes(self, report: PruningReport) -> None:
        """
        對長期未存取且顯著性極低的情節節點加上 archived 標記。
        （不物理刪除，保留供未來審計；僅從即時檢索空間排除）
        """
        try:
            result = self._client.episodic.query(
                """
                MATCH (e:Episode)
                WHERE e.salience_score < 0.1
                  AND e.is_dreamed = true
                  AND e.timestamp < $cutoff
                SET e.archived = true
                RETURN count(e) AS archived
                """,
                params={"cutoff": _days_ago_iso(self._ARCHIVE_DAYS)},
            )
            count = _extract_count(result)
            report.nodes_archived = count
            if count > 0:
                report.details.append(f"歸檔 {count} 個過期低顯著性情節")
        except Exception as exc:
            report.details.append(f"節點歸檔失敗：{exc}")

    # ── 3. 更新 max_frequency 正規化基準 ─────────────────────────────────────

    def _update_max_frequency(self, report: PruningReport) -> None:
        """
        重新計算語意圖譜中 RELATES_TO 邊緣的最大頻率值，
        作為後續邊緣權重計算的正規化基準。
        結果存為一個特殊的 SystemMeta 節點。
        """
        try:
            result = self._client.semantic.ro_query(
                """
                MATCH ()-[r:RELATES_TO]->()
                RETURN max(r.frequency) AS max_freq
                """
            )
            max_freq = 1
            if result.result_set and result.result_set[0][0]:
                max_freq = int(result.result_set[0][0])

            self._client.semantic.query(
                """
                MERGE (m:SystemMeta {key: 'max_frequency'})
                SET m.value = $val, m.updated_at = $now
                """,
                params={"val": max_freq, "now": now_iso()},
            )
            report.max_frequency_updated = max_freq
            report.details.append(f"max_frequency 更新為 {max_freq}")
        except Exception as exc:
            report.details.append(f"max_frequency 更新失敗：{exc}")

    # ── 4. 跨域橋接（頓悟機制）──────────────────────────────────────────────

    def _create_latent_bridges(self, report: PruningReport) -> None:
        """
        在語意圖譜中找出向量相近但未連結的概念對，
        建立 LATENT_BRIDGE 邊緣（跨域潛意識捷徑）。

        演算法：
          1. 掃描所有 Concept 節點（取前 50 個，避免計算爆炸）
          2. 兩兩計算向量相似度（使用 FalkorDB 向量索引 kNN）
          3. 過濾：距離夠近 AND 尚無直接連結
          4. 建立 LATENT_BRIDGE
        """
        try:
            # 取得所有有向量嵌入的 Concept ID 列表（限 50 個）
            result = self._client.semantic.ro_query(
                "MATCH (c:Concept) RETURN c.id AS id, c.name AS name LIMIT 50"
            )
            concepts = [(row[0], row[1]) for row in result.result_set]

            if len(concepts) < 2:
                report.details.append("概念節點不足，跳過橋接")
                return

            bridges_created = 0

            for i, (cid, cname) in enumerate(concepts):
                if bridges_created >= self._MAX_BRIDGES_PER_RUN:
                    break

                # 用 kNN 找最近鄰（排除自身）
                neighbors = self._client.semantic.ro_query(
                    """
                    MATCH (src:Concept {id: $id})
                    CALL db.idx.vector.queryNodes('Concept', 'embedding', 5, src.embedding)
                    YIELD node, score
                    WHERE node.id <> $id AND score >= $sim_threshold
                    RETURN node.id AS nid, node.name AS nname, score
                    """,
                    params={
                        "id": cid,
                        "sim_threshold": self._BRIDGE_SIMILARITY_THRESHOLD,
                    },
                )

                for nrow in neighbors.result_set:
                    nid = nrow[0]

                    # 確認尚無直接連結（RELATES_TO 或 LATENT_BRIDGE）
                    existing = self._client.semantic.ro_query(
                        """
                        MATCH (u:Concept {id: $uid})-[r:RELATES_TO|LATENT_BRIDGE]->(v:Concept {id: $vid})
                        RETURN count(r) AS cnt
                        """,
                        params={"uid": cid, "vid": nid},
                    )
                    if existing.result_set and existing.result_set[0][0] > 0:
                        continue

                    # 建立橋接
                    nname = nrow[1]
                    score = nrow[2]
                    self._client.semantic.query(
                        """
                        MATCH (u:Concept {id: $uid}), (v:Concept {id: $vid})
                        CREATE (u)-[:LATENT_BRIDGE {
                            reason: $reason,
                            similarity: $score,
                            created_at: $now
                        }]->(v)
                        """,
                        params={
                            "uid": cid,
                            "vid": nid,
                            "reason": f"夢境橋接：{cname} ↔ {nname}（相似度 {score:.3f}）",
                            "score": score,
                            "now": now_iso(),
                        },
                    )
                    bridges_created += 1
                    report.bridges_created += 1
                    report.details.append(f"橋接：{cname} ↔ {nname}")

                    if bridges_created >= self._MAX_BRIDGES_PER_RUN:
                        break

        except Exception as exc:
            report.details.append(f"跨域橋接失敗：{exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_count(result: Any) -> int:
    """安全提取 Cypher 查詢的 count 回傳值。"""
    try:
        if result and result.result_set and result.result_set[0][0] is not None:
            return int(result.result_set[0][0])
    except Exception:
        pass
    return 0


def _days_ago_iso(days: int) -> str:
    """計算 N 天前的 ISO 時間字串。"""
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(days=days)).isoformat()
