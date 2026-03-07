"""
soul/affect/salience.py

情感顯著性評估器：計算每次互動的「記憶烙印強度」。
對應大腦分區：杏仁核 (Amygdala) — 決定哪些記憶值得被深刻保留

設計原理：
  顯著性分數 = 情緒強度 × 新穎性 × 任務重要性
  這個分數決定了 Episode 節點的 da_weight 與 salience_score。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from soul.affect.neurochem import NeurochemState


@dataclass
class SalienceSignals:
    """收集各種顯著性訊號來源。"""
    user_feedback: float = 0.0       # 明確使用者回饋（-1.0 到 1.0）
    task_complexity: float = 0.5     # 任務複雜度（0~1）
    novelty_score: float = 0.5       # 新穎性（0~1）
    error_occurred: bool = False     # 是否發生錯誤
    was_corrected: bool = False      # 是否需要基底核修正
    verification_score: float = 1.0  # 基底核一致性分數


class SalienceEvaluator:
    """
    計算互動的情感顯著性分數，用於：
    1. Episode 節點的 da_weight（記憶烙印深度）
    2. 邊緣權重的 salience 分量
    3. NeurochemState 更新觸發
    """

    def evaluate(
        self,
        signals: SalienceSignals,
        state: NeurochemState,
        user_message: str = "",
        agent_response: str = "",
    ) -> tuple[float, float, float]:
        """
        計算顯著性指標。

        Returns:
            (salience_score, da_weight, ht_weight)
            - salience_score: 整體顯著性 [0~1]
            - da_weight: 多巴胺烙印強度 [0~1]
            - ht_weight: 血清素穩定性標記 [0~1]
        """
        # 基礎顯著性：由任務複雜度與新穎性決定
        base_salience = (signals.task_complexity * 0.4 + signals.novelty_score * 0.4)

        # 使用者情緒強度（從文字中估算，若無明確回饋）
        text_sentiment = _estimate_sentiment_intensity(user_message)

        # 使用者明確回饋（如 👍 / 👎）加權最重
        feedback_weight = signals.user_feedback * 0.5

        # 錯誤事件具高顯著性（失敗也值得記住）
        error_bonus = 0.3 if signals.error_occurred else 0.0

        # 需要修正的互動：顯著性稍高，但 DA 不飆升
        correction_penalty = 0.1 if signals.was_corrected else 0.0

        # 最終顯著性
        salience = _clamp(
            base_salience
            + abs(feedback_weight)
            + text_sentiment * 0.1
            + error_bonus
        )

        # 多巴胺烙印強度：正向回饋時高，錯誤時低
        if signals.user_feedback > 0.3:
            da_weight = _clamp(state.dopamine + signals.user_feedback * 0.3)
        elif signals.error_occurred:
            da_weight = _clamp(state.dopamine - 0.2)
        else:
            da_weight = state.dopamine

        # 血清素穩定性標記：驗證分數高時穩定，修正時略高
        ht_weight = _clamp(
            state.serotonin * 0.7
            + signals.verification_score * 0.3
            + (correction_penalty if signals.was_corrected else 0)
        )

        return round(salience, 3), round(da_weight, 3), round(ht_weight, 3)

    def update_neurochem(
        self,
        state: NeurochemState,
        signals: SalienceSignals,
    ) -> None:
        """根據本次互動的顯著性訊號更新神經化學狀態。"""
        if signals.user_feedback > 0.5:
            state.on_success(reward=signals.user_feedback * 0.4)
        elif signals.user_feedback < -0.3:
            state.on_failure(penalty=abs(signals.user_feedback) * 0.3)

        if signals.novelty_score > 0.75:
            state.on_discovery(novelty=signals.novelty_score * 0.3)

        if signals.task_complexity > 0.7 and signals.error_occurred:
            state.on_uncertainty(level=0.25)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _estimate_sentiment_intensity(text: str) -> float:
    """
    從使用者訊息中快速估算情緒強度（0~1）。
    僅作為輔助信號，非主要判斷依據。
    """
    if not text:
        return 0.0

    # 正向關鍵詞
    positive_patterns = [
        r"謝謝|感謝|太好了|完美|棒|讚|好|對|正確|喜歡|幫助|有用",
        r"thank|great|perfect|excellent|good|correct|helpful|awesome",
        r"👍|✅|🎉|⭐",
    ]
    # 負向關鍵詞
    negative_patterns = [
        r"錯|不對|不好|差|問題|失望|沒用|廢|糟|爛",
        r"wrong|bad|error|problem|fail|useless|terrible",
        r"👎|❌|😤|😠",
    ]

    positive_count = sum(
        len(re.findall(p, text, re.IGNORECASE)) for p in positive_patterns
    )
    negative_count = sum(
        len(re.findall(p, text, re.IGNORECASE)) for p in negative_patterns
    )

    total = positive_count + negative_count
    if total == 0:
        return 0.2  # 中性，略有顯著性

    return _clamp((positive_count - negative_count) / total * 0.5 + 0.5)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
