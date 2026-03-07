"""
soul/dream/distillation.py

知識蒸餾模組：從情節記憶中提取抽象語意規則。
對應大腦分區：預設模式網路（DMN）— 睡眠中的記憶整合與語意抽象化

設計原理：
  1. 掃描 soul_episodic 中重複出現的拓撲模式（Motifs）
  2. 以 LLM 對模式進行抽象化壓縮 → 通用規則
  3. 在 soul_semantic 建立新的 Rule / Concept 節點
  4. 建立 DERIVED_FROM 邊緣，保留知識溯源
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic
from openai import OpenAI

from soul.core.config import settings
from soul.memory.episodic import EpisodicMemory
from soul.memory.graph import GraphClient, new_id, now_iso
from soul.memory.semantic import SemanticMemory


@dataclass
class DistillationReport:
    """知識蒸餾週期的執行報告。"""
    patterns_found: int = 0
    rules_created: int = 0
    concepts_created: int = 0
    details: list[str] = field(default_factory=list)


class KnowledgeDistillation:
    """
    情節→語意知識蒸餾器。

    流程：
      掃描 soul_episodic 近期情節
      → LLM 識別重複主題/問題模式
      → 抽象化為通用規則節點
      → 寫入 soul_semantic

    Usage:
        distiller = KnowledgeDistillation(graph_client)
        report = distiller.run()
    """

    _DISTILL_SYSTEM = """你是一個知識蒸餾專家。
給定一組 AI 對話片段，請識別其中的共同主題、問題模式，並提取可重用的抽象規則。

請以 JSON 格式回覆：
{
  "patterns": [
    {
      "name": "規則/概念名稱（簡短）",
      "type": "rule" | "concept" | "abstraction",
      "description": "詳細說明這個規則或概念",
      "domain": "領域標籤（如 finance / coding / general）"
    }
  ]
}

若無明顯可提取的規則，請回傳 {"patterns": []}。
"""

    def __init__(self, client: GraphClient) -> None:
        self._episodic = EpisodicMemory(client)
        self._semantic = SemanticMemory(client)
        self._client = client
        self._provider = settings.soul_llm_provider.lower()
        if self._provider == "openrouter":
            self._llm = OpenAI(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key or "no-key",
            )
            self._or_headers = {"HTTP-Referer": "https://opensoul.ai", "X-Title": "OpenSoul"}
        else:
            self._llm_anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            self._or_headers = {}
        self._model = settings.soul_llm_model

    def run(self, recent_limit: int = 30, min_cluster_size: int = 2) -> DistillationReport:
        """
        執行一個蒸餾週期。

        Args:
            recent_limit:     掃描最近幾個情節
            min_cluster_size: 最少幾個相似情節才觸發蒸餾

        Returns:
            DistillationReport 包含執行統計
        """
        report = DistillationReport()

        # 1. 取得近期情節內容
        episodes = self._get_recent_episodes(limit=recent_limit)
        if not episodes:
            report.details.append("無情節可供蒸餾")
            return report

        # 2. 按主題聚類（使用簡單的關鍵詞共現分組）
        clusters = self._cluster_by_keywords(episodes, min_cluster_size)
        report.patterns_found = len(clusters)

        if not clusters:
            report.details.append("未發現足夠重複的主題模式")
            return report

        # 3. 對每個叢集進行 LLM 蒸餾
        for cluster_key, cluster_episodes in clusters.items():
            try:
                extracted = self._distill_cluster(cluster_episodes)
                for pattern in extracted:
                    self._save_pattern(pattern, cluster_episodes, report)
            except Exception as exc:
                report.details.append(f"叢集 '{cluster_key}' 蒸餾失敗：{exc}")

        return report

    # ── Private ───────────────────────────────────────────────────────────────

    def _get_recent_episodes(self, limit: int) -> list[dict[str, Any]]:
        """取得最近的情節（按時間降序）。"""
        result = self._client.episodic.ro_query(
            """
            MATCH (e:Episode)
            RETURN e ORDER BY e.timestamp DESC LIMIT $limit
            """,
            params={"limit": limit},
        ).result_set
        return [dict(row[0].properties) for row in result]

    def _cluster_by_keywords(
        self,
        episodes: list[dict[str, Any]],
        min_size: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        以關鍵詞共現做簡易聚類。
        提取每個情節 content 的前 3 個中文詞組作為叢集鍵。
        """
        import re

        clusters: dict[str, list[dict]] = {}
        zh_pattern = re.compile(r"[\u4e00-\u9fff]{2,6}")

        for ep in episodes:
            content = ep.get("content", "") + ep.get("user_input", "")
            tokens = zh_pattern.findall(content)
            if not tokens:
                continue

            # 以前 2 個詞組作為叢集鍵
            key = "_".join(tokens[:2]) if len(tokens) >= 2 else tokens[0]
            clusters.setdefault(key, []).append(ep)

        # 過濾：只保留達到 min_size 的叢集
        return {k: v for k, v in clusters.items() if len(v) >= min_size}

    def _distill_cluster(self, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        將一組情節交給 LLM 蒸餾為抽象規則列表。
        最多取 10 個情節的 content 欄位。
        """
        snippets = []
        for ep in episodes[:10]:
            u = ep.get("user_input", "")[:100]
            a = ep.get("agent_response", "")[:150]
            snippets.append(f"Q: {u}\nA: {a}")

        combined = "\n---\n".join(snippets)
        prompt = f"以下是一組相似的對話片段，請提取可重用的規則或概念：\n\n{combined}"

        if self._provider == "openrouter":
            resp = self._llm.chat.completions.create(
                model=self._model,
                max_tokens=512,
                temperature=settings.soul_llm_temperature,
                extra_headers=self._or_headers,
                messages=[
                    {"role": "system", "content": self._DISTILL_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content or ""
        else:
            msg = self._llm_anthropic.messages.create(
                model=self._model,
                max_tokens=512,
                temperature=settings.soul_llm_temperature,
                system=self._DISTILL_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            return data.get("patterns", [])
        return []

    def _save_pattern(
        self,
        pattern: dict[str, Any],
        source_episodes: list[dict[str, Any]],
        report: DistillationReport,
    ) -> None:
        """將蒸餾出的規則/概念寫入 soul_semantic 圖譜。"""
        name = pattern.get("name", "").strip()
        ptype = pattern.get("type", "rule")
        desc = pattern.get("description", "")

        if not name or not desc:
            return

        if ptype == "rule":
            domain = pattern.get("domain", "general")
            self._semantic.upsert_rule(
                condition=name,
                action=desc,
                domain=domain,
                confidence=0.75,
            )
            report.rules_created += 1
            report.details.append(f"蒸餾規則：{name} [{domain}]")

        else:
            # concept / abstraction
            cid = self._semantic.upsert_concept(
                name=name,
                description=desc,
                concept_type=ptype,
            )

            # 建立 DERIVED_FROM 邊緣（來源情節 → 新概念）
            for ep in source_episodes[:3]:
                try:
                    self._client.semantic.query(
                        """
                        MATCH (c:Concept {id: $cid})
                        MERGE (e_ref:EpisodeRef {id: $eid})
                        MERGE (c)-[:DERIVED_FROM]->(e_ref)
                        """,
                        params={"cid": cid, "eid": ep.get("id", "")},
                    )
                except Exception:
                    pass

            report.concepts_created += 1
            report.details.append(f"蒸餾概念：{name}")
