"""
tests/test_affect.py

情感系統單元測試：NeurochemState 與 SalienceEvaluator。
"""

from __future__ import annotations

import pytest

from soul.affect.neurochem import NeurochemMode, NeurochemState
from soul.affect.salience import SalienceEvaluator, SalienceSignals


# ── NeurochemState ────────────────────────────────────────────────────────────

class TestNeurochemState:
    def test_default_balanced(self) -> None:
        state = NeurochemState()
        assert state.dopamine == pytest.approx(0.5)
        assert state.serotonin == pytest.approx(0.5)
        assert state.mode == NeurochemMode.BALANCED

    def test_on_success_raises_dopamine(self) -> None:
        state = NeurochemState(dopamine=0.5, serotonin=0.5)
        state.on_success(reward=0.3)
        assert state.dopamine > 0.5
        assert state.serotonin < 0.5   # 5-HT 略降

    def test_on_failure_lowers_dopamine(self) -> None:
        state = NeurochemState(dopamine=0.8, serotonin=0.3)
        state.on_failure(penalty=0.2)
        assert state.dopamine < 0.8
        assert state.serotonin > 0.3   # 5-HT 上升

    def test_on_uncertainty_raises_serotonin(self) -> None:
        state = NeurochemState(dopamine=0.5, serotonin=0.4)
        state.on_uncertainty(level=0.3)
        assert state.serotonin > 0.4

    def test_values_clamped_0_to_1(self) -> None:
        state = NeurochemState(dopamine=0.95, serotonin=0.05)
        state.on_success(reward=1.0)
        assert 0.0 <= state.dopamine <= 1.0
        assert 0.0 <= state.serotonin <= 1.0

    def test_mode_high_dopamine(self) -> None:
        # EXCITED 條件：da >= 0.75 AND ht < 0.4
        # 設 serotonin=0.5 讓 EXCITED 條件 (ht < 0.4) 不成立，落入 HIGH_DOPAMINE
        state = NeurochemState(dopamine=0.75, serotonin=0.5)
        assert state.mode == NeurochemMode.HIGH_DOPAMINE

    def test_mode_high_serotonin(self) -> None:
        state = NeurochemState(dopamine=0.4, serotonin=0.75)
        assert state.mode == NeurochemMode.HIGH_SEROTONIN

    def test_mode_excited(self) -> None:
        state = NeurochemState(dopamine=0.9, serotonin=0.2)
        assert state.mode == NeurochemMode.EXCITED

    def test_mode_cautious(self) -> None:
        state = NeurochemState(dopamine=0.2, serotonin=0.8)
        assert state.mode == NeurochemMode.CAUTIOUS

    def test_learning_rate_range(self) -> None:
        for da in [0.0, 0.5, 1.0]:
            state = NeurochemState(dopamine=da, serotonin=0.5)
            lr = state.learning_rate
            assert 0.0 <= lr <= 1.0

    def test_verification_threshold_increases_with_serotonin(self) -> None:
        low_ht = NeurochemState(dopamine=0.5, serotonin=0.2)
        high_ht = NeurochemState(dopamine=0.5, serotonin=0.9)
        assert high_ht.verification_threshold > low_ht.verification_threshold

    def test_natural_decay_toward_balance(self) -> None:
        state = NeurochemState(dopamine=1.0, serotonin=0.0)
        state.natural_decay(hours=10.0)
        assert state.dopamine < 1.0   # 向 0.5 衰減
        assert state.serotonin > 0.0

    def test_reset_to_balanced(self) -> None:
        state = NeurochemState(dopamine=0.9, serotonin=0.1)
        state.reset_to_balanced()
        assert state.dopamine == pytest.approx(0.5)
        assert state.serotonin == pytest.approx(0.5)

    def test_from_dict_roundtrip(self) -> None:
        original = NeurochemState(dopamine=0.7, serotonin=0.4)
        d = original.to_dict()
        # from_dict 支援 dopamine_level / serotonin_level 鍵（SOUL.md frontmatter 格式）
        restored = NeurochemState.from_dict({
            "dopamine_level": d["dopamine"],
            "serotonin_level": d["serotonin"],
        })
        assert restored.dopamine == pytest.approx(original.dopamine, abs=0.001)
        assert restored.serotonin == pytest.approx(original.serotonin, abs=0.001)


# ── SalienceEvaluator ─────────────────────────────────────────────────────────

class TestSalienceEvaluator:
    def setup_method(self) -> None:
        self.evaluator = SalienceEvaluator()
        self.state = NeurochemState()

    def test_positive_feedback_high_salience(self) -> None:
        signals = SalienceSignals(user_feedback=1.0, task_complexity=0.5, novelty_score=0.5)
        sal, da, ht = self.evaluator.evaluate(signals, self.state)
        assert sal > 0.5

    def test_error_boosts_salience(self) -> None:
        signals = SalienceSignals(error_occurred=True, task_complexity=0.5, novelty_score=0.5)
        sal, da, ht = self.evaluator.evaluate(signals, self.state)
        assert sal > 0.4   # 錯誤也值得記憶

    def test_output_range(self) -> None:
        """評估結果應在 [0, 1] 範圍內。"""
        signals = SalienceSignals(
            user_feedback=0.8,
            task_complexity=0.7,
            novelty_score=0.9,
            error_occurred=False,
        )
        sal, da, ht = self.evaluator.evaluate(signals, self.state)
        assert 0.0 <= sal <= 1.0
        assert 0.0 <= da <= 1.0
        assert 0.0 <= ht <= 1.0

    def test_update_neurochem_on_success(self) -> None:
        da_before = self.state.dopamine
        signals = SalienceSignals(user_feedback=0.9)
        self.evaluator.update_neurochem(self.state, signals)
        assert self.state.dopamine > da_before
