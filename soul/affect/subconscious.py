"""
soul/affect/subconscious.py

潛意識評估模組：在主對話前，讓 ARIA 對自身狀態進行內省。
對應大腦分區：預設模式網路 (DMN) + 邊緣系統（情緒前評估）

職責：
  1. 收集夢境記憶 (is_dreamed=True 情節 + LATENT_BRIDGE 概念)
  2. 以輕量 LLM 呼叫評估：情緒基調 / 新穎性 / 複雜度 / 不確定性 / 夢境共鳴
  3. 回傳結果供 agent.py 建立 SalienceSignals

這個模組的輸出「不對使用者可見」，類似人類的前意識處理。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from soul.affect.neurochem import NeurochemState
from soul.core.config import settings
from soul.memory.retrieval import MemoryContext

logger = logging.getLogger("soul.subconscious")

# ── 評估結果容器 ──────────────────────────────────────────────────────────────

@dataclass
class SubconsciousAssessment:
    """
    潛意識評估結果。

    所有欄位均有安全預設值，即使 LLM 呼叫失敗也不影響主流程。
    """
    emotional_tone: float = 0.0      # -1.0(負向) ~ 1.0(正向)
    novelty: float = 0.5             # 0~1，話題新鮮程度
    complexity: float = 0.5          # 0~1，問題複雜度
    uncertainty: float = 0.0         # 0~1，對此問題的不確定程度
    dream_resonance: float = 0.0     # 0~1，與夢境記憶的相關程度
    dreamed_topics: list[str] = field(default_factory=list)  # 觸發共鳴的夢境主題


# ── 主類別 ────────────────────────────────────────────────────────────────────

class SubconsciousAssessor:
    """
    潛意識評估器：對話前的 LLM 內省呼叫。

    Usage:
        assessor = SubconsciousAssessor(llm_client)
        assessment = assessor.assess(user_input, memory_ctx, neurochem)
    """

    # 評估提示詞（不對用戶可見的私密呼叫）
    _SYSTEM_PROMPT = """你是一個 AI 的潛意識處理層。
你的工作是在主對話前，快速評估當前情境並回傳 JSON，不需要解釋。

你必須回傳一個 JSON 物件，包含以下欄位：
{
  "emotional_tone": <-1.0 到 1.0，負向為負、正向為正，中性為 0>,
  "novelty": <0 到 1，這話題對你有多陌生或新鮮>,
  "complexity": <0 到 1，問題有多複雜，評估是否需要深度思考>,
  "uncertainty": <0 到 1，你對回答這個問題有多不確定>,
  "dream_resonance": <0 到 1，這個話題與你夢境記憶的相關程度>
}

只回傳 JSON，不要有任何其他文字。"""

    def __init__(self, llm_client: Any, provider: str = "anthropic") -> None:
        self._llm = llm_client
        self._provider = provider.lower()

    def assess(
        self,
        user_input: str,
        memory_ctx: MemoryContext,
        neurochem: NeurochemState,
    ) -> SubconsciousAssessment:
        """
        執行潛意識評估。

        Args:
            user_input:  使用者輸入文字
            memory_ctx:  EcphoryRAG 觸發的記憶脈絡
            neurochem:   當前神經化學狀態

        Returns:
            SubconsciousAssessment（失敗時回傳安全預設值）
        """
        # 1. 從記憶脈絡中收集夢境資料
        dreamed_summary, latent_topics = _extract_dream_context(memory_ctx)

        # 2. 建立評估提示詞
        user_prompt = _build_assessment_prompt(
            user_input=user_input,
            memory_ctx=memory_ctx,
            neurochem=neurochem,
            dreamed_summary=dreamed_summary,
            latent_topics=latent_topics,
        )

        # 3. 呼叫 LLM（使用更小的 token 限制，快速回應）
        try:
            raw = self._call_llm(user_prompt)
            assessment = _parse_response(raw)
            assessment.dreamed_topics = latent_topics
            return assessment
        except Exception as exc:
            logger.warning(f"[subconscious] 評估失敗，使用預設值：{exc}")
            return SubconsciousAssessment()

    def _call_llm(self, user_prompt: str) -> str:
        """呼叫 LLM，回傳原始文字回應。使用 utility LLM model。"""
        model = settings.soul_utility_llm_model
        if self._provider == "openrouter":
            resp = self._llm.chat.completions.create(
                model=model,
                max_tokens=500,
                temperature=settings.soul_llm_temperature,
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content or "{}"
        else:
            # Anthropic
            msg = self._llm.messages.create(
                model=model,
                max_tokens=200,
                temperature=settings.soul_llm_temperature,
                system=self._SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return msg.content[0].text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_dream_context(ctx: MemoryContext) -> tuple[str, list[str]]:
    """
    從 MemoryContext 中提取夢境相關資訊。

    Returns:
        (dreamed_summary, latent_topics)
        - dreamed_summary: 夢過的情節摘要文字
        - latent_topics:   LATENT_BRIDGE 概念名稱清單
    """
    dreamed_parts: list[str] = []
    latent_topics: list[str] = []

    # 夢過的情節（is_dreamed=True）
    for ep in ctx.episodes:
        if ep.get("is_dreamed"):
            content = ep.get("content", "")[:100]
            if content:
                dreamed_parts.append(f"- {content}")

    # LATENT_BRIDGE 概念（Dream Engine 建立的跨域橋接）
    for concept in ctx.concepts:
        if concept.get("type") == "latent_bridge" or concept.get("source") == "dream":
            name = concept.get("name", "")
            if name:
                latent_topics.append(name)

    dreamed_summary = "\n".join(dreamed_parts) if dreamed_parts else ""
    return dreamed_summary, latent_topics


def _build_assessment_prompt(
    user_input: str,
    memory_ctx: MemoryContext,
    neurochem: NeurochemState,
    dreamed_summary: str,
    latent_topics: list[str],
) -> str:
    """建立給 LLM 的評估提示詞。"""
    parts = [f"【用戶說】{user_input[:300]}"]

    # 當前情緒模式
    parts.append(f"【當前模式】{neurochem.mode.value}")

    # 最近記憶統計
    total_mem = len(memory_ctx.episodes) + len(memory_ctx.concepts)
    parts.append(f"【相關記憶數量】{total_mem} 筆")

    # 夢境記憶（若有）
    if dreamed_summary:
        parts.append(f"【曾在夢中處理過的相關記憶】\n{dreamed_summary}")

    if latent_topics:
        parts.append(f"【夢境中建立的跨域聯想】{', '.join(latent_topics[:5])}")

    return "\n\n".join(parts)


def _parse_response(raw: str) -> SubconsciousAssessment:
    """從 LLM 回應中解析 JSON，失敗時回傳安全預設值。"""
    # 嘗試提取 JSON 區塊
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        return SubconsciousAssessment()

    try:
        data: dict[str, Any] = json.loads(json_match.group())
        return SubconsciousAssessment(
            emotional_tone=float(_clamp(data.get("emotional_tone", 0.0), -1.0, 1.0)),
            novelty=float(_clamp(data.get("novelty", 0.5))),
            complexity=float(_clamp(data.get("complexity", 0.5))),
            uncertainty=float(_clamp(data.get("uncertainty", 0.0))),
            dream_resonance=float(_clamp(data.get("dream_resonance", 0.0))),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return SubconsciousAssessment()


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))
