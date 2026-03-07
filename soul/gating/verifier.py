"""
soul/gating/verifier.py

ResponseVerifier：一致性驗證閘門。
模擬大腦基底核（Basal Ganglia）的「Go/NoGo」競爭機制。

設計哲學：
  - 驗證為輔助，不阻斷正常對話。
  - 空圖譜 / 無記憶時，預設保守通過（score=1.0）。
  - score 由多個 sub-score 加權構成，每個維度獨立計算。

分數構成（各維度加權）：
  - 長度與品質基線（0.2）：回覆非空且長度合理
  - 新穎性一致（0.3）：回覆中的概念是否與已知記憶吻合
  - 規則遵守（0.3）：是否違反 Rule 節點的條件
  - 矛盾懲罰（-0.5 at most）：明確矛盾命中時扣分

對應大腦分區：基底核（Basal Ganglia）— 動作選擇與抑制
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from soul.affect.neurochem import NeurochemState
from soul.memory.retrieval import MemoryContext


# ── VerificationResult ────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """
    ResponseVerifier 的驗證結果容器。

    Attributes:
        score:          整體一致性分數 [0.0 ~ 1.0]
        passed:         是否通過 verification_threshold
        threshold:      決策所用的閾值（來自 NeurochemState）
        reasons:        通過的佐證列表（正向）
        contradictions: 矛盾發現列表（警告，不一定直接阻斷）
    """
    score: float
    passed: bool
    threshold: float
    reasons: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "passed": self.passed,
            "threshold": round(self.threshold, 3),
            "reasons": self.reasons,
            "contradictions": self.contradictions,
        }


# ── ResponseVerifier ──────────────────────────────────────────────────────────

class ResponseVerifier:
    """
    LLM 回覆的一致性驗證器。

    在 SoulAgent.chat() Step 4（LLM 呼叫）之後執行，
    評估回覆與現有記憶的一致性，輸出 VerificationResult。

    Usage:
        verifier = ResponseVerifier()
        result = verifier.verify(response_text, memory_ctx, neurochem)
        if not result.passed:
            # 交給 Inhibitor 處理
    """

    # ── 各維度權重 ─────────────────────────────────────────────────────────────
    _W_QUALITY     = 0.20   # 基礎品質（長度 / 非空）
    _W_CONSISTENCY = 0.30   # 概念一致性
    _W_RULE        = 0.30   # 規則遵守度
    _W_NOVELTY     = 0.20   # 新知識合理性（保留額度）
    _CONTRADICTION_PENALTY = 0.50  # 每個矛盾命中最多扣分上限

    def verify(
        self,
        response_text: str,
        memory_ctx: MemoryContext,
        neurochem: NeurochemState,
    ) -> VerificationResult:
        """
        執行完整驗證流程。

        Args:
            response_text: LLM 生成的回覆文字
            memory_ctx:    EcphoryRAG 觸發的記憶脈絡
            neurochem:     當前神經化學狀態（決定閾值）

        Returns:
            VerificationResult 包含 score、passed、reasons、contradictions
        """
        threshold = neurochem.verification_threshold
        reasons: list[str] = []
        contradictions: list[str] = []

        # ── 1. 基礎品質檢查 ──────────────────────────────────────────────────
        quality_score = self._check_quality(response_text, reasons)

        # ── 2. 概念一致性檢查 ────────────────────────────────────────────────
        if memory_ctx.concepts:
            consistency_score = self._check_concept_consistency(
                response_text, memory_ctx.concepts, reasons, contradictions
            )
        else:
            consistency_score = 1.0   # 無概念記憶 → 無從矛盾，通過

        # ── 3. 規則遵守檢查 ──────────────────────────────────────────────────
        if memory_ctx.concepts:
            rule_score = self._check_rule_compliance(
                response_text, memory_ctx.concepts, reasons, contradictions
            )
        else:
            rule_score = 1.0   # 無規則記憶 → 保守通過

        # ── 4. 矛盾懲罰 ──────────────────────────────────────────────────────
        # 每個矛盾扣 0.1，但上限為 0.5
        contradiction_penalty = min(
            len(contradictions) * 0.1,
            self._CONTRADICTION_PENALTY,
        )

        # ── 5. 加權分數 ──────────────────────────────────────────────────────
        score = (
            self._W_QUALITY     * quality_score
            + self._W_CONSISTENCY * consistency_score
            + self._W_RULE        * rule_score
            + self._W_NOVELTY     * 1.0          # 新知識保留分
            - contradiction_penalty
        )
        score = max(0.0, min(1.0, score))

        passed = score >= threshold

        if passed:
            reasons.append(f"整體分數 {score:.2f} >= 閾值 {threshold:.2f}")
        else:
            contradictions.append(f"整體分數 {score:.2f} < 閾值 {threshold:.2f}")

        return VerificationResult(
            score=round(score, 3),
            passed=passed,
            threshold=round(threshold, 3),
            reasons=reasons,
            contradictions=contradictions,
        )

    # ── Private Checks ────────────────────────────────────────────────────────

    def _check_quality(self, text: str, reasons: list[str]) -> float:
        """
        基礎品質評估：非空、長度合理、非純重複。
        """
        stripped = text.strip()
        if not stripped:
            return 0.0

        # 極短回覆（< 5 字元）扣分
        if len(stripped) < 5:
            return 0.3

        # 重複字元比例過高（可能是模型崩潰）
        if len(set(stripped)) < max(3, len(stripped) // 10):
            return 0.4

        reasons.append("回覆長度與品質正常")
        return 1.0

    def _check_concept_consistency(
        self,
        response_text: str,
        concepts: list[dict],
        reasons: list[str],
        contradictions: list[str],
    ) -> float:
        """
        檢查回覆中的概念與記憶中已知概念的一致性。
        透過簡單關鍵詞比對：若回覆提到已知概念，視為一致。
        """
        if not concepts:
            return 1.0

        known_names = [
            c.get("name", "").strip()
            for c in concepts
            if c.get("name")
        ]
        if not known_names:
            return 1.0

        response_lower = response_text.lower()
        mentioned = [n for n in known_names if n.lower() in response_lower]

        if mentioned:
            reasons.append(f"回覆提及已知概念：{', '.join(mentioned[:3])}")
            return 1.0

        # 未提及任何已知概念，中性分數
        return 0.7

    def _check_rule_compliance(
        self,
        response_text: str,
        concepts: list[dict],
        reasons: list[str],
        contradictions: list[str],
    ) -> float:
        """
        若記憶中存在 Rule 節點（type='rule'），檢查回覆是否違反條件。

        Rule 節點格式：
          - condition：觸發條件關鍵詞（若此詞出現在回覆，表示場景命中）
          - action：期望動作（若 action 未出現在回覆，視為違規）
        """
        rule_concepts = [
            c for c in concepts
            if c.get("type", "") == "rule"
            and c.get("description", "")
        ]

        if not rule_concepts:
            return 1.0   # 無規則 → 無從違反

        response_lower = response_text.lower()
        violations = []

        for rule in rule_concepts[:5]:   # 最多檢查 5 條規則
            condition = rule.get("name", "").lower()
            description = rule.get("description", "").lower()

            # 若回覆觸發了條件，但描述中的限制詞出現在違規模式中
            if condition and condition in response_lower:
                # 簡易違規模式：規則描述含「禁止」「不可」「never」
                forbidden_patterns = [r"禁止", r"不可", r"never", r"forbidden", r"must not"]
                for pat in forbidden_patterns:
                    if re.search(pat, description, re.IGNORECASE):
                        violations.append(f"疑似違反規則：{rule.get('name', '')}")
                        break

        if violations:
            contradictions.extend(violations)
            return max(0.3, 1.0 - len(violations) * 0.2)

        reasons.append("未發現規則違反")
        return 1.0
