"""
tests/test_semantic.py

語義記憶系統的單元測試，驗證多義詞、同義詞檢測等新功能。
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from soul.memory.semantic import SemanticMemory
from soul.affect.neurochem import NeurochemState
from soul.memory.retrieval import compute_retrieval_params


class TestPolysemy:
    """多義詞功能測試。"""

    def test_add_sense(self):
        """測試為概念添加新含義。"""
        # Mock GraphClient
        mock_graph = MagicMock()
        mock_client = MagicMock()
        mock_client.semantic = mock_graph

        semantic = SemanticMemory(mock_client)

        # 模擬 get_concept 返回（需要 .properties 屬性）
        mock_node = MagicMock()
        mock_node.properties = {
            "id": "c1",
            "name": "蘋果",
            "description": "水果",
            "polysemy_dict": "{}",
        }
        mock_graph.ro_query.return_value.result_set = [[mock_node]]

        # 添加新含義
        sense_id = semantic.add_sense(
            concept_id="c1",
            sense_text="美國科技公司",
            emotion_tag="technology",
            examples=["我買了蘋果公司的股票"],
        )

        # 驗證返回值
        assert sense_id is not None
        assert len(sense_id) > 0

        # 驗證 query 被呼叫
        mock_graph.query.assert_called()

    def test_get_primary_sense(self):
        """測試獲取主要含義。"""
        mock_graph = MagicMock()
        mock_client = MagicMock()
        mock_client.semantic = mock_graph

        semantic = SemanticMemory(mock_client)

        # 模擬多義詞字典
        polysemy_dict = {
            "sense1": {"text": "水果蘋果", "salience": 0.8},
            "sense2": {"text": "科技公司", "salience": 0.6},
        }

        mock_node = MagicMock()
        mock_node.properties = {
            "id": "c1",
            "name": "蘋果",
            "description": "概念",
            "polysemy_dict": json.dumps(polysemy_dict),
        }
        mock_graph.ro_query.return_value.result_set = [[mock_node]]

        primary = semantic.get_primary_sense("c1")

        # 驗證主要含義是最高顯著性的
        assert primary["sense_id"] == "sense1"
        assert primary["salience"] == 0.8

    def test_update_sense_salience(self):
        """測試更新含義顯著性。"""
        mock_graph = MagicMock()
        mock_client = MagicMock()
        mock_client.semantic = mock_graph

        semantic = SemanticMemory(mock_client)

        polysemy_dict = {
            "sense1": {"text": "含義1", "salience": 0.5},
            "sense2": {"text": "含義2", "salience": 0.3},
        }

        mock_node = MagicMock()
        mock_node.properties = {
            "id": "c1",
            "polysemy_dict": json.dumps(polysemy_dict),
        }
        mock_graph.ro_query.return_value.result_set = [[mock_node]]

        # 增加 sense2 的顯著性
        semantic.update_sense_salience("c1", "sense2", +0.2)

        # 驗證 query 被呼叫並更新
        mock_graph.query.assert_called()


class TestSynonymDetection:
    """同義詞檢測功能測試。"""

    def test_detect_synonyms(self):
        """測試向量相似度同義詞檢測。"""
        mock_graph = MagicMock()
        mock_client = MagicMock()
        mock_client.semantic = mock_graph

        semantic = SemanticMemory(mock_client)

        # 模擬向量查詢結果（平坦列表，每行是 (id, name, score)）
        results = [
            ("concept_1", "快速", 0.92),
            ("concept_2", "飛快", 0.88),
        ]
        mock_graph.ro_query.return_value.result_set = results

        embedding = [0.1] * 1536
        similar = semantic.detect_synonyms(
            embedding=embedding,
            similarity_threshold=0.85,
            max_matches=5,
        )

        assert len(similar) == 2
        assert similar[0][2] >= 0.85  # 相似度足夠

    def test_link_synonyms(self):
        """測試同義詞關聯。"""
        mock_graph = MagicMock()
        mock_client = MagicMock()
        mock_client.semantic = mock_graph

        semantic = SemanticMemory(mock_client)

        # 模擬 get_concept
        mock_node = MagicMock()
        mock_node.properties = {"id": "new_c", "name": "飛快"}
        mock_graph.ro_query.return_value.result_set = [[mock_node]]

        semantic.link_synonyms(
            new_concept_id="new_c",
            canonical_concept_id="canonical_c",
            confidence=0.92,
        )

        # 驗證邊被建立
        mock_graph.query.assert_called()


class TestNeurochemControl:
    """神經化學調控改進測試。"""

    def test_on_success_smooth_adjustment(self):
        """測試成功事件的緩和式調控。"""
        state = NeurochemState()
        initial_da = state.dopamine

        # 模擬成功事件
        state.on_success(reward=0.3)

        # 驗證多巴胺平緩上升
        assert initial_da < state.dopamine  # 有上升
        assert state.dopamine < 0.85  # 但有上限

        # 驗證血清素略微下降
        assert state.serotonin < 0.5

    def test_on_failure_smooth_adjustment(self):
        """測試失敗事件的緩和式調控。"""
        state = NeurochemState()
        state.dopamine = 0.7

        state.on_failure(penalty=0.2)

        # 驗證多巴胺平緩下降
        assert state.dopamine < 0.7  # 下降
        assert state.dopamine >= 0.2  # 但有下限

        # 驗證血清素上升
        assert state.serotonin > 0.5

    def test_natural_decay_speed(self):
        """測試自然衰減速度。"""
        state = NeurochemState()
        state.dopamine = 0.8

        # 衰減 1 小時
        state.natural_decay(hours=1.0)

        # 驗證：5% 衰減，DA 從 0.8 應該趨向 0.6+
        # 衰減後 DA = 0.5 + (0.8-0.5) * (1-0.05) = 0.5 + 0.285 ≈ 0.785
        assert 0.75 < state.dopamine < 0.85

        # 衰減 14 小時，應該更接近平衡
        state.dopamine = 0.8
        state.natural_decay(hours=14.0)
        # decay_factor = max(0.8, 1.0 - 0.05*14) = 0.8
        # DA = 0.5 + (0.8-0.5)*0.8 = 0.5 + 0.24 = 0.74
        assert 0.7 < state.dopamine < 0.75


class TestRetrievalParams:
    """記憶檢索動態參數測試。"""

    def test_compute_retrieval_params_smooth(self):
        """測試檢索參數的非線性調制。"""
        # 測試血清素影響
        seed_k_low, breadth_k_low, _ = compute_retrieval_params(serotonin=0.3, dopamine=0.5)
        seed_k_high, breadth_k_high, _ = compute_retrieval_params(serotonin=0.8, dopamine=0.5)

        assert seed_k_low < seed_k_high
        assert breadth_k_low < breadth_k_high

        # 測試多巴胺影響
        _, _, threshold_low = compute_retrieval_params(serotonin=0.5, dopamine=0.2)
        _, _, threshold_high = compute_retrieval_params(serotonin=0.5, dopamine=0.8)

        assert threshold_low > threshold_high  # DA 高時閾值更低（更開放）

    def test_retrieval_params_smoothness(self):
        """測試參數變化的平緩性。"""
        thresholds = []
        for da in [0.2, 0.35, 0.5, 0.65, 0.8]:
            _, _, threshold = compute_retrieval_params(serotonin=0.5, dopamine=da)
            thresholds.append(threshold)

        # 驗證相鄰步長的變化
        deltas = [abs(thresholds[i + 1] - thresholds[i]) for i in range(len(thresholds) - 1)]
        # 所有變化都應該小於 0.08（相對平緩）
        assert all(d < 0.08 for d in deltas), f"變化過大: {deltas}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
