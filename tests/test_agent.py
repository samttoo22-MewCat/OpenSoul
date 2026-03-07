"""
tests/test_agent.py

Phase 6 Smoke Test：驗證 SoulAgent.chat() 完整流程。

所有外部依賴（OpenAI embedding、Anthropic Claude、FalkorDB）
均使用 unittest.mock.patch 替換，不需真實 API 金鑰或資料庫連線。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Sys path（確保從專案根目錄可以 import）──────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from soul.core.agent import AgentResponse, EmbeddingService, SoulAgent
from soul.core.session import Session
from soul.memory.retrieval import MemoryContext


# ── Fixtures ──────────────────────────────────────────────────────────────────

ZERO_EMBEDDING = [0.0] * 1536
FAKE_LLM_REPLY = "這是來自 Mock Claude 的測試回覆。"


def _make_mock_graph_client() -> MagicMock:
    """建立完全 Mock 的 GraphClient（三圖譜方法均回傳空結果）。"""
    mock = MagicMock()

    # 每個圖譜的 ro_query 回傳空結果集
    empty_result = MagicMock()
    empty_result.result_set = []
    mock.semantic.ro_query.return_value = empty_result
    mock.episodic.ro_query.return_value = empty_result
    mock.procedural.ro_query.return_value = empty_result

    # write 方法回傳 None
    mock.semantic.query.return_value = None
    mock.episodic.query.return_value = None
    mock.procedural.query.return_value = None

    return mock


# ── Test: EmbeddingService ────────────────────────────────────────────────────

class TestEmbeddingService:
    def test_zero_vector_dimension(self):
        """zero_vector() 應回傳正確維度的零向量。"""
        svc = EmbeddingService.__new__(EmbeddingService)
        svc._dim = 1536
        vec = svc.zero_vector()
        assert len(vec) == 1536
        assert all(v == 0.0 for v in vec)

    @patch("soul.core.agent.OpenAI")
    def test_embed_calls_api(self, mock_openai_cls):
        """embed() 應呼叫 OpenAI API 並回傳嵌入向量。"""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        fake_embedding = MagicMock()
        fake_embedding.data = [MagicMock(embedding=ZERO_EMBEDDING)]
        mock_client.embeddings.create.return_value = fake_embedding

        svc = EmbeddingService()
        result = svc.embed("測試文字")

        assert result == ZERO_EMBEDDING
        mock_client.embeddings.create.assert_called_once()

    @patch("soul.core.agent.OpenAI")
    def test_embed_empty_text_returns_zero(self, mock_openai_cls):
        """空字串輸入應直接回傳零向量，不呼叫 API。"""
        svc = EmbeddingService()
        result = svc.embed("   ")
        assert len(result) == 1536
        mock_openai_cls.return_value.embeddings.create.assert_not_called()


# ── Test: Session Extensions ──────────────────────────────────────────────────

class TestSessionExtensions:
    def test_turn_count_initial_zero(self):
        sess = Session()
        assert sess.turn_count == 0

    def test_last_episode_id_initial_none(self):
        sess = Session()
        assert sess.last_episode_id is None


# ── Test: SoulAgent ───────────────────────────────────────────────────────────

class TestSoulAgent:
    def _patch_all(self):
        """回傳所有需要 patch 的路徑清單（作為 context manager 使用）。"""
        return [
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic"),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
            patch("soul.core.agent.EmbeddingService.embed", return_value=ZERO_EMBEDDING),
        ]

    def _make_agent_and_session(self, tmp_path: Path):
        """建立帶有 Mock SOUL.md 的 SoulAgent 與新 Session。"""
        soul_md = tmp_path / "SOUL.md"
        soul_md.write_text(
            "---\nname: TestSOUL\ndopamine_level: 0.5\nserotonin_level: 0.5\n---\n# 測試人格\n",
            encoding="utf-8",
        )
        agent = SoulAgent(workspace=tmp_path)
        session = Session()
        return agent, session

    def test_agent_instantiation(self, tmp_path: Path):
        """SoulAgent 應可在 Mock 環境中正常實例化。"""
        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic"),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
        ):
            agent = SoulAgent(workspace=tmp_path)
            assert agent is not None
            assert agent.soul.name == "openSOUL"  # 無 SOUL.md 時回傳預設值

    def test_agent_loads_soul_md(self, tmp_path: Path):
        """有 SOUL.md 時，應正確載入人格名稱。"""
        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic"),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
        ):
            agent, _ = self._make_agent_and_session(tmp_path)
            assert agent.soul.name == "TestSOUL"

    def test_chat_returns_agent_response(self, tmp_path: Path):
        """chat() 應回傳 AgentResponse，且 text 不為空。"""
        mock_llm_message = MagicMock()
        mock_llm_message.content = [MagicMock(text=FAKE_LLM_REPLY)]
        mock_llm = MagicMock()
        mock_llm.messages.create.return_value = mock_llm_message

        mock_graph = _make_mock_graph_client()
        # write_episode 要回傳一個假的 episode_id
        mock_graph.episodic.query.return_value = None

        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic", return_value=mock_llm),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=mock_graph),
            patch("soul.core.agent.EmbeddingService.embed", return_value=ZERO_EMBEDDING),
        ):
            agent, session = self._make_agent_and_session(tmp_path)
            response = agent.chat("你好，請介紹你自己", session)

        assert isinstance(response, AgentResponse)
        assert response.text == FAKE_LLM_REPLY
        assert response.session_id == session.session_id
        assert isinstance(response.episode_id, str)
        assert len(response.episode_id) > 0

    def test_chat_updates_turn_count(self, tmp_path: Path):
        """chat() 後 session.turn_count 應增加 1。"""
        mock_llm_message = MagicMock()
        mock_llm_message.content = [MagicMock(text=FAKE_LLM_REPLY)]
        mock_llm = MagicMock()
        mock_llm.messages.create.return_value = mock_llm_message

        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic", return_value=mock_llm),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
            patch("soul.core.agent.EmbeddingService.embed", return_value=ZERO_EMBEDDING),
        ):
            agent, session = self._make_agent_and_session(tmp_path)
            assert session.turn_count == 0
            agent.chat("第一輪對話", session)
            assert session.turn_count == 1
            agent.chat("第二輪對話", session)
            assert session.turn_count == 2

    def test_chat_neurochem_in_response(self, tmp_path: Path):
        """AgentResponse.neurochem 應包含 dopamine 和 serotonin。"""
        mock_llm_message = MagicMock()
        mock_llm_message.content = [MagicMock(text=FAKE_LLM_REPLY)]
        mock_llm = MagicMock()
        mock_llm.messages.create.return_value = mock_llm_message

        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic", return_value=mock_llm),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
            patch("soul.core.agent.EmbeddingService.embed", return_value=ZERO_EMBEDDING),
        ):
            agent, session = self._make_agent_and_session(tmp_path)
            response = agent.chat("測試神經化學回傳", session)

        assert "dopamine" in response.neurochem
        assert "serotonin" in response.neurochem
        assert 0.0 <= response.neurochem["dopamine"] <= 1.0
        assert 0.0 <= response.neurochem["serotonin"] <= 1.0

    def test_chat_memory_context_is_memory_context(self, tmp_path: Path):
        """AgentResponse.memory_context 應為 MemoryContext 實例。"""
        mock_llm_message = MagicMock()
        mock_llm_message.content = [MagicMock(text="OK")]
        mock_llm = MagicMock()
        mock_llm.messages.create.return_value = mock_llm_message

        with (
            patch("soul.core.agent.OpenAI"),
            patch("soul.core.agent.anthropic.Anthropic", return_value=mock_llm),
            patch("soul.core.agent.initialize_schemas"),
            patch("soul.core.agent.get_graph_client", return_value=_make_mock_graph_client()),
            patch("soul.core.agent.EmbeddingService.embed", return_value=ZERO_EMBEDDING),
        ):
            agent, session = self._make_agent_and_session(tmp_path)
            response = agent.chat("記憶脈絡測試", session)

        assert isinstance(response.memory_context, MemoryContext)


# ── Test: Helper Functions ────────────────────────────────────────────────────

class TestHelpers:
    def test_extract_noun_phrases_chinese(self):
        from soul.core.agent import _extract_noun_phrases
        text = "今天天氣很好，適合去公園散步。人工智能的發展令人驚嘆。"
        nouns = _extract_noun_phrases(text)
        assert isinstance(nouns, list)
        assert len(nouns) > 0

    def test_extract_noun_phrases_dedup(self):
        from soul.core.agent import _extract_noun_phrases
        text = "機器學習 機器學習 機器學習"
        nouns = _extract_noun_phrases(text)
        assert nouns.count("機器學習") == 1

    def test_estimate_complexity_short(self):
        from soul.core.agent import _estimate_complexity
        score = _estimate_complexity("你好")
        assert 0.0 <= score <= 0.3  # 短文字應得低分

    def test_estimate_complexity_long(self):
        from soul.core.agent import _estimate_complexity
        long_text = "請分析以下資料：" + "A " * 300
        score = _estimate_complexity(long_text)
        assert score > 0.5  # 長文字應得高分

    def test_estimate_novelty_empty_context(self):
        from soul.core.agent import _estimate_novelty
        ctx = MemoryContext()
        assert _estimate_novelty(ctx) == 0.8  # 無記憶 → 高新穎性

    def test_estimate_novelty_rich_context(self):
        from soul.core.agent import _estimate_novelty
        ctx = MemoryContext(
            episodes=[{"id": str(i)} for i in range(10)],
            concepts=[{"id": str(i)} for i in range(5)],
        )
        assert _estimate_novelty(ctx) < 0.5  # 豐富記憶 → 低新穎性
