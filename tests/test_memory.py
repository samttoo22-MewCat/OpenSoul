"""
tests/test_memory.py

記憶系統單元測試（不需要 FalkorDB 連線）。
測試邊緣權重計算、EcphoryRAG 資料結構、記憶脈絡序列化。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from soul.memory.graph import compute_edge_weight
from soul.memory.retrieval import MemoryContext


# ── compute_edge_weight ───────────────────────────────────────────────────────

class TestComputeEdgeWeight:
    """動態邊緣權重計算函數測試。"""

    def test_fresh_edge_high_recency(self) -> None:
        """剛建立的邊緣近期性接近 1.0。"""
        weight = compute_edge_weight(
            last_accessed=datetime.utcnow(),
            frequency=1,
            salience=0.5,
        )
        assert weight > 0.5, f"新邊緣權重應 > 0.5，實際 {weight}"

    def test_old_edge_low_recency(self) -> None:
        """30 天未存取的邊緣近期性應大幅衰減。"""
        old_time = datetime.utcnow() - timedelta(days=30)
        weight = compute_edge_weight(
            last_accessed=old_time,
            frequency=1,
            salience=0.0,
        )
        # Recency = exp(-0.01 * 30*24) = exp(-7.2) ≈ 0.00074
        assert weight < 0.15, f"舊邊緣權重應 < 0.15，實際 {weight}"

    def test_high_frequency_boosts_weight(self) -> None:
        """高頻存取應顯著提升權重。"""
        w_low = compute_edge_weight(
            last_accessed=datetime.utcnow() - timedelta(hours=1),
            frequency=1,
            salience=0.3,
            max_frequency=100,
        )
        w_high = compute_edge_weight(
            last_accessed=datetime.utcnow() - timedelta(hours=1),
            frequency=80,
            salience=0.3,
            max_frequency=100,
        )
        assert w_high > w_low, "高頻存取應得到更高權重"

    def test_high_salience_boosts_weight(self) -> None:
        """高情感顯著性應提升權重。"""
        w_low_sal = compute_edge_weight(
            last_accessed=datetime.utcnow(),
            frequency=5,
            salience=0.0,
        )
        w_high_sal = compute_edge_weight(
            last_accessed=datetime.utcnow(),
            frequency=5,
            salience=1.0,
        )
        assert w_high_sal > w_low_sal

    def test_weight_clamped_0_to_1(self) -> None:
        """任何輸入下，權重必須在 [0, 1] 範圍內。"""
        for freq in [0, 1, 1000]:
            for sal in [0.0, 0.5, 1.0]:
                w = compute_edge_weight(
                    last_accessed=datetime.utcnow(),
                    frequency=freq,
                    salience=sal,
                    max_frequency=max(freq, 1),  # 確保 freq_score <= 1.0
                )
                # 函數本身不 clamp，但權重公式上界為 alpha+beta+gamma=1.0
                assert 0.0 <= w <= 1.01, f"權重超出範圍：{w}"

    def test_custom_alpha_beta_gamma(self) -> None:
        """支援自訂 α β γ 參數。"""
        w = compute_edge_weight(
            last_accessed=datetime.utcnow(),
            frequency=10,
            salience=0.8,
            alpha=0.5,
            beta=0.3,
            gamma=0.2,
        )
        assert isinstance(w, float)


# ── MemoryContext ─────────────────────────────────────────────────────────────

class TestMemoryContext:
    """MemoryContext 資料結構與序列化測試。"""

    def test_empty_context_is_empty(self) -> None:
        ctx = MemoryContext()
        assert ctx.is_empty() is True

    def test_context_with_episodes_not_empty(self) -> None:
        ctx = MemoryContext()
        ctx.episodes = [{"id": "e1", "content": "測試情節"}]
        assert ctx.is_empty() is False

    def test_to_text_empty(self) -> None:
        ctx = MemoryContext()
        assert ctx.to_text() == ""

    def test_to_text_with_episodes(self) -> None:
        ctx = MemoryContext()
        ctx.episodes = [
            {"content": "使用者問了 FalkorDB 的問題", "salience_score": 0.8},
        ]
        text = ctx.to_text()
        assert "FalkorDB" in text
        assert "相關對話記憶" in text

    def test_to_text_with_concepts(self) -> None:
        ctx = MemoryContext()
        ctx.concepts = [
            {"name": "知識圖譜", "description": "節點與邊的網路結構"},
        ]
        text = ctx.to_text()
        assert "知識圖譜" in text
        assert "語意概念" in text

    def test_to_text_with_procedures(self) -> None:
        ctx = MemoryContext()
        ctx.procedures = [
            {"name": "資料分析 SOP", "steps": ["載入資料", "清洗", "分析"]},
        ]
        text = ctx.to_text()
        assert "資料分析 SOP" in text
        assert "程序" in text

    def test_to_text_limits_items(self) -> None:
        """to_text 最多顯示 5 個情節，不超出 context 限制。"""
        ctx = MemoryContext()
        ctx.episodes = [
            {"content": f"情節 {i}", "salience_score": 0.5}
            for i in range(20)
        ]
        text = ctx.to_text()
        # 最多 5 條，不顯示全部 20 條
        count = text.count("  - 情節")
        assert count <= 5
