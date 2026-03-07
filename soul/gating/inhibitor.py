"""
soul/gating/inhibitor.py

SubconsciousInhibitor：潛意識抑制迴路。
模擬前額葉皮質（Prefrontal Cortex）對衝動行為的抑制與修正。

三種輸出動作：
  PASS     — 回覆通過閾值，直接輸出
  REVISE   — 回覆信心略低，插入免責標記後輸出（不重試）
  SUPPRESS — 回覆信心極低，抑制並觸發重試（LiDER 機制）

與 ResponseVerifier 的分工：
  Verifier  → 「這個回覆有多可信？」（給出 score）
  Inhibitor → 「面對這個 score，我該怎麼做？」（給出 action）

對應大腦分區：前額葉（PFC）— 衝動控制、決策修正
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from soul.affect.neurochem import NeurochemState
from soul.gating.verifier import VerificationResult


# ── InhibitionAction ──────────────────────────────────────────────────────────

class InhibitionAction(str, Enum):
    """
    抑制迴路決策動作。

    PASS:     分數 >= threshold → 直接輸出Original text
    REVISE:   threshold*0.7 <= score < threshold → 加前綴免責標記後輸出
    SUPPRESS: score < threshold*0.7 → 抑制本次回覆，請求重試
    """
    PASS     = "pass"
    REVISE   = "revise"
    SUPPRESS = "suppress"


# ── InhibitionResult ──────────────────────────────────────────────────────────

@dataclass
class InhibitionResult:
    """
    SubconsciousInhibitor.gate() 的輸出容器。

    Attributes:
        action:            決策動作（PASS / REVISE / SUPPRESS）
        text:              最終輸出文字（REVISE 時已加前綴；SUPPRESS 時為原始文字）
        inhibition_reason: 決策理由（用於日誌與 AgentResponse）
        attempt:           本次為第幾次嘗試（0-based）
        score:             當前驗證分數（mirror from VerificationResult）
    """
    action: InhibitionAction
    text: str
    inhibition_reason: str
    attempt: int = 0
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "inhibition_reason": self.inhibition_reason,
            "attempt": self.attempt,
            "score": round(self.score, 3),
        }


# ── SubconsciousInhibitor ─────────────────────────────────────────────────────

# 免責標記模板
_REVISE_PREFIX = "⚠️ *（以下回覆信心略低，請自行判斷）*\n\n"


class SubconsciousInhibitor:
    """
    潛意識抑制迴路。

    根據 VerificationResult 決定輸出策略：
      - PASS：直接輸出，正向強化神經化學
      - REVISE：加免責前綴後輸出，中性神經化學
      - SUPPRESS：抑制输出，負向懲罰神經化學，要求重試

    Usage:
        inhibitor = SubconsciousInhibitor()
        result = inhibitor.gate(response_text, verify_result, neurochem, attempt=0)
        if result.action == InhibitionAction.SUPPRESS:
            # retry...
    """

    # REVISE 決策邊界（threshold 的比例）
    _REVISE_RATIO = 0.7

    def gate(
        self,
        response_text: str,
        verify_result: VerificationResult,
        neurochem: NeurochemState,
        attempt: int = 0,
    ) -> InhibitionResult:
        """
        執行抑制決策。

        Args:
            response_text:  LLM 生成的原始回覆文字
            verify_result:  ResponseVerifier.verify() 的結果
            neurochem:      當前神經化學狀態（用於觸發懲罰/獎勵）
            attempt:        當前重試次數（0-based）

        Returns:
            InhibitionResult 包含決策動作與最終輸出文字
        """
        score     = verify_result.score
        threshold = verify_result.threshold
        revise_boundary = threshold * self._REVISE_RATIO

        # ── PASS ──────────────────────────────────────────────────────────────
        if score >= threshold:
            return InhibitionResult(
                action=InhibitionAction.PASS,
                text=response_text,
                inhibition_reason=f"驗證通過（score={score:.2f} >= {threshold:.2f}）",
                attempt=attempt,
                score=score,
            )

        # ── REVISE ────────────────────────────────────────────────────────────
        if score >= revise_boundary:
            revised = _REVISE_PREFIX + response_text
            reason = (
                f"信心略低（score={score:.2f}, 閾值={threshold:.2f}），"
                f"已加入免責標記"
            )
            if verify_result.contradictions:
                reason += f"；發現：{', '.join(verify_result.contradictions[:2])}"
            return InhibitionResult(
                action=InhibitionAction.REVISE,
                text=revised,
                inhibition_reason=reason,
                attempt=attempt,
                score=score,
            )

        # ── SUPPRESS ──────────────────────────────────────────────────────────
        # 信心極低 → 觸發神經化學懲罰，要求重試
        penalty = min(0.3, threshold - score)
        neurochem.on_failure(penalty=penalty)

        reason = (
            f"回覆被抑制（score={score:.2f} < {revise_boundary:.2f}），"
            f"第 {attempt + 1} 次嘗試，觸發重試"
        )
        if verify_result.contradictions:
            reason += f"；矛盾：{', '.join(verify_result.contradictions[:2])}"

        return InhibitionResult(
            action=InhibitionAction.SUPPRESS,
            text=response_text,   # 保留原文（萬一重試耗盡時使用）
            inhibition_reason=reason,
            attempt=attempt,
            score=score,
        )

    @staticmethod
    def should_retry(
        inhibit_result: InhibitionResult,
        max_retries: int,
    ) -> bool:
        """
        判斷是否應繼續重試。

        Args:
            inhibit_result: 本次 gate() 的結果
            max_retries:    最大允許重試次數

        Returns:
            True 若動作為 SUPPRESS 且尚未超過重試上限
        """
        return (
            inhibit_result.action == InhibitionAction.SUPPRESS
            and inhibit_result.attempt < max_retries
        )
