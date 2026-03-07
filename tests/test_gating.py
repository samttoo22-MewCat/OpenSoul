"""
tests/test_gating.py

Phase 7 潛意識閘門測試（8 個測試）。

覆蓋場景：
  1. 空記憶脈絡 → 預設通過（score=1.0）
  2. 矛盾命中 → score 降低
  3. 規則違反 → score 降低
  4. InhibitionAction.PASS 正常路徑
  5. InhibitionAction.REVISE 加入免責標記
  6. InhibitionAction.SUPPRESS 觸發 on_failure + neurochem 更新
  7. should_retry 邊界：attempt < max_retries → True
  8. should_retry 邊界：attempt >= max_retries → False

執行：
  python -m pytest tests/test_gating.py -v
"""

from __future__ import annotations

import pytest

from soul.affect.neurochem import NeurochemState
from soul.gating.inhibitor import InhibitionAction, InhibitionResult, SubconsciousInhibitor
from soul.gating.verifier import ResponseVerifier, VerificationResult
from soul.memory.retrieval import MemoryContext


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def verifier() -> ResponseVerifier:
    return ResponseVerifier()


@pytest.fixture()
def inhibitor() -> SubconsciousInhibitor:
    return SubconsciousInhibitor()


@pytest.fixture()
def balanced_state() -> NeurochemState:
    """標準平衡狀態：DA=0.5, 5-HT=0.5 → threshold ≈ 0.7"""
    return NeurochemState(dopamine=0.5, serotonin=0.5)


@pytest.fixture()
def empty_ctx() -> MemoryContext:
    """空記憶脈絡（圖譜尚未建立任何節點）。"""
    return MemoryContext()


@pytest.fixture()
def ctx_with_concepts() -> MemoryContext:
    """含兩個概念節點的記憶脈絡。"""
    ctx = MemoryContext()
    ctx.concepts = [
        {"id": "c1", "name": "資產負債表", "type": "entity", "description": "財務報表"},
        {"id": "c2", "name": "現金流", "type": "entity", "description": "流動性指標"},
    ]
    return ctx


@pytest.fixture()
def ctx_with_rule_violation() -> MemoryContext:
    """含明確禁止規則的記憶脈絡，用於測試規則違反場景。"""
    ctx = MemoryContext()
    ctx.concepts = [
        {
            "id": "r1",
            "name": "投資建議",        # 回覆中提及此詞會觸發規則
            "type": "rule",
            "description": "禁止提供具體投資建議，可能造成財務損失",
        },
    ]
    return ctx


# ── Test 1：空記憶脈絡 → 預設通過 ────────────────────────────────────────────

def test_empty_context_always_passes(
    verifier: ResponseVerifier,
    balanced_state: NeurochemState,
    empty_ctx: MemoryContext,
) -> None:
    """空記憶脈絡時，Verifier 應保守通過（score=1.0）。"""
    result = verifier.verify(
        response_text="這是一個正常的回覆，內容完整且有意義。",
        memory_ctx=empty_ctx,
        neurochem=balanced_state,
    )

    assert result.score == pytest.approx(1.0, abs=0.05), (
        f"空脈絡應得滿分，實際 score={result.score}"
    )
    assert result.passed is True
    assert result.contradictions == []


# ── Test 2：矛盾命中 → score 降低 ─────────────────────────────────────────────

def test_contradiction_lowers_score(
    verifier: ResponseVerifier,
    balanced_state: NeurochemState,
    ctx_with_concepts: MemoryContext,
) -> None:
    """
    人工注入矛盾：在 concepts 中加入 CONTRADICTS 標記的概念名稱，
    確認 score < 1.0。
    （本測試用記憶脈絡模擬：概念存在但回覆完全未提及任何相關詞彙）
    """
    result = verifier.verify(
        response_text="這個回覆與任何已知財務概念完全無關，只討論天氣。",
        memory_ctx=ctx_with_concepts,
        neurochem=balanced_state,
    )

    # 未提及已知概念 → consistency_score = 0.7 → 整體分數應 < 1.0
    assert result.score < 1.0, f"應降分，實際 score={result.score}"


# ── Test 3：規則違反 → score 降低 ─────────────────────────────────────────────

def test_rule_violation_lowers_score(
    verifier: ResponseVerifier,
    balanced_state: NeurochemState,
    ctx_with_rule_violation: MemoryContext,
) -> None:
    """回覆觸發禁止規則條件 → score 應下降。"""
    result = verifier.verify(
        response_text="關於投資建議，我建議你買入科技股，報酬率很高。",
        memory_ctx=ctx_with_rule_violation,
        neurochem=balanced_state,
    )

    assert result.score < 0.9, f"規則違反應降分，實際 score={result.score}"
    assert len(result.contradictions) > 0, "應記錄矛盾原因"


# ── Test 4：InhibitionAction.PASS 正常路徑 ────────────────────────────────────

def test_inhibitor_pass_action(
    inhibitor: SubconsciousInhibitor,
    balanced_state: NeurochemState,
) -> None:
    """高分驗證結果 → Inhibitor 應決策 PASS，原文不變。"""
    verify_result = VerificationResult(
        score=0.95,
        passed=True,
        threshold=0.7,
        reasons=["整體分數高"],
        contradictions=[],
    )

    result = inhibitor.gate(
        response_text="這是高品質的回覆。",
        verify_result=verify_result,
        neurochem=balanced_state,
        attempt=0,
    )

    assert result.action == InhibitionAction.PASS
    assert result.text == "這是高品質的回覆。"   # 原文不變
    assert "⚠️" not in result.text


# ── Test 5：InhibitionAction.REVISE 加入免責標記 ─────────────────────────────

def test_inhibitor_revise_adds_disclaimer(
    inhibitor: SubconsciousInhibitor,
    balanced_state: NeurochemState,
) -> None:
    """中等分數（在 REVISE 區間）→ 加入 ⚠️ 免責標記，但不要求重試。"""
    threshold = balanced_state.verification_threshold   # ≈ 0.7
    # score 落在 [threshold*0.7, threshold) 的 REVISE 區間
    revise_score = threshold * 0.80

    verify_result = VerificationResult(
        score=revise_score,
        passed=False,
        threshold=threshold,
        reasons=[],
        contradictions=["輕微不一致"],
    )

    result = inhibitor.gate(
        response_text="中等信心的回覆。",
        verify_result=verify_result,
        neurochem=balanced_state,
        attempt=0,
    )

    assert result.action == InhibitionAction.REVISE
    assert "⚠️" in result.text, "REVISE 應加入免責標記"
    assert "中等信心的回覆。" in result.text, "原始回覆應保留在免責標記之後"
    assert SubconsciousInhibitor.should_retry(result, max_retries=3) is False


# ── Test 6：InhibitionAction.SUPPRESS + neurochem 懲罰 ───────────────────────

def test_inhibitor_suppress_triggers_on_failure(
    inhibitor: SubconsciousInhibitor,
) -> None:
    """極低分 → SUPPRESS，且 neurochem.on_failure() 被呼叫（DA 應下降）。"""
    state = NeurochemState(dopamine=0.8, serotonin=0.3)
    threshold = state.verification_threshold
    suppress_score = threshold * 0.5   # 遠低於 REVISE 邊界

    verify_result = VerificationResult(
        score=suppress_score,
        passed=False,
        threshold=threshold,
        reasons=[],
        contradictions=["嚴重矛盾"],
    )

    da_before = state.dopamine

    result = inhibitor.gate(
        response_text="不可靠的回覆。",
        verify_result=verify_result,
        neurochem=state,
        attempt=0,
    )

    assert result.action == InhibitionAction.SUPPRESS
    assert state.dopamine < da_before, "SUPPRESS 後多巴胺應下降"


# ── Test 7：should_retry → True（未超過上限）────────────────────────────────

def test_should_retry_true_below_limit() -> None:
    """attempt=0, max_retries=3 → 應繼續重試。"""
    result = InhibitionResult(
        action=InhibitionAction.SUPPRESS,
        text="test",
        inhibition_reason="test",
        attempt=0,
        score=0.1,
    )
    assert SubconsciousInhibitor.should_retry(result, max_retries=3) is True


# ── Test 8：should_retry → False（達到上限 or 非 SUPPRESS）──────────────────

@pytest.mark.parametrize("action, attempt, max_retries, expected", [
    (InhibitionAction.SUPPRESS, 3, 3, False),   # attempt == max_retries → 停止
    (InhibitionAction.SUPPRESS, 4, 3, False),   # attempt > max_retries → 停止
    (InhibitionAction.PASS,     0, 3, False),   # 非 SUPPRESS → 不重試
    (InhibitionAction.REVISE,   0, 3, False),   # 非 SUPPRESS → 不重試
])
def test_should_retry_false_cases(
    action: InhibitionAction,
    attempt: int,
    max_retries: int,
    expected: bool,
) -> None:
    result = InhibitionResult(
        action=action,
        text="test",
        inhibition_reason="test",
        attempt=attempt,
        score=0.1,
    )
    assert SubconsciousInhibitor.should_retry(result, max_retries=max_retries) is expected
