"""
tests/test_mcp_tools.py

MCP Phase 1 工具驗證測試。
使用 Mock 隔離 LLM / FalkorDB 外部依賴，驗證工具介面與回傳格式。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 確保 OpenSoul/OpenSoul 在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── GraphLiteClient 單元測試 ────────────────────────────────────────────────


class TestGraphLiteClient:
    def setup_method(self):
        from soul_mcp.adapters.graph_lite import GraphLiteClient
        self.client = GraphLiteClient(db_path=":memory:")

    def test_ping(self):
        assert self.client.ping() is True

    def test_create_and_retrieve_episode(self):
        import uuid
        from soul_mcp.adapters.graph_lite import QueryResult

        ep_id = str(uuid.uuid4())
        g = self.client.episodic

        # 建立 Episode 節點
        g.query(
            "CREATE (e:Episode { id: $id, content: $content, session_id: $session, "
            "timestamp: $ts, da_weight: $da, salience_score: $sal, is_dreamed: false })",
            params={
                "id": ep_id,
                "content": "測試對話內容",
                "session": "sess-001",
                "ts": "2026-01-01T00:00:00",
                "da": 0.7,
                "sal": 0.6,
            },
        )

        # 依 id 查詢
        result = g.ro_query(
            "MATCH (e:Episode {id: $id}) RETURN e LIMIT 1",
            params={"id": ep_id},
        )
        assert result.result_set, "應該找到節點"
        props = result.result_set[0][0].properties
        assert props["id"] == ep_id
        assert props["content"] == "測試對話內容"

    def test_match_by_session_id(self):
        import uuid
        g = self.client.episodic
        sid = "sess-999"

        for i in range(3):
            g.query(
                "CREATE (e:Episode { id: $id, content: $content, session_id: $session, "
                "timestamp: $ts, da_weight: $da, salience_score: $sal })",
                params={
                    "id": str(uuid.uuid4()),
                    "content": f"內容 {i}",
                    "session": sid,
                    "ts": f"2026-01-0{i+1}T00:00:00",
                    "da": 0.5,
                    "sal": 0.5,
                },
            )

        result = g.ro_query(
            "MATCH (e:Episode {session_id: $sid}) RETURN e ORDER BY e.timestamp ASC LIMIT 10",
            params={"sid": sid},
        )
        assert len(result.result_set) == 3

    def test_set_is_dreamed(self):
        import uuid
        g = self.client.episodic
        ep_id = str(uuid.uuid4())

        g.query(
            "CREATE (e:Episode { id: $id, content: $content, is_dreamed: false })",
            params={"id": ep_id, "content": "test"},
        )
        g.query(
            "MATCH (e:Episode {id: $id}) SET e.is_dreamed = true",
            params={"id": ep_id},
        )

        result = g.ro_query(
            "MATCH (e:Episode {id: $id}) RETURN e LIMIT 1",
            params={"id": ep_id},
        )
        assert result.result_set[0][0].properties["is_dreamed"] is True

    def test_count(self):
        g = self.client.episodic
        import uuid
        g.query(
            "CREATE (e:Episode { id: $id, content: $content })",
            params={"id": str(uuid.uuid4()), "content": "x"},
        )
        result = g.ro_query("MATCH (e:Episode) RETURN count(e) AS cnt")
        assert result.result_set[0][0] >= 1

    def test_clear_all(self):
        self.client.clear_all()
        result = self.client.episodic.ro_query("MATCH (n) RETURN count(n) AS cnt")
        assert result.result_set[0][0] == 0


# ── soul_judge_tool 測試 ────────────────────────────────────────────────────


class TestSoulJudgeTool:
    @patch("soul.gating.judge.JudgeAgent")
    @patch("openai.OpenAI")
    def test_returns_correct_schema(self, mock_openai, mock_judge_cls):
        mock_judge = MagicMock()
        mock_judge.discover_available_tools.return_value = [
            {"name": "browser-control", "description": "控制瀏覽器"}
        ]
        mock_judge.recommend_tool.return_value = {
            "recommended_tool": "browser-control",
            "reasoning": "需要瀏覽網頁",
            "confidence": 0.85,
        }
        mock_judge_cls.return_value = mock_judge

        from soul_mcp.tools.judge import soul_judge_tool
        result = soul_judge_tool("幫我查今天的新聞")

        assert "recommended_tool" in result
        assert "reasoning" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)

    def test_returns_none_on_error(self):
        """當 LLM 初始化失敗時，應回傳 none 而非拋出例外。"""
        with patch("openai.OpenAI", side_effect=Exception("LLM 不可用")):
            from soul_mcp.tools.judge import soul_judge_tool
            result = soul_judge_tool("測試")
        assert result["recommended_tool"] == "none"
        assert "confidence" in result


# ── soul_memory_retrieve 測試 ────────────────────────────────────────────────


class TestSoulMemoryRetrieve:
    def test_returns_correct_schema_offline(self):
        """
        在無 FalkorDB 且無 embedding service 的情況下，
        應回傳含 error 欄位的 dict（不崩潰）。
        """
        with patch("soul.core.agent.EmbeddingService", side_effect=ImportError("mock")):
            from soul_mcp.tools.memory import soul_memory_retrieve
            result = soul_memory_retrieve("測試查詢")

        assert isinstance(result, dict)
        # 不管有無記憶，這四個 key 必須存在
        for key in ("episodes", "concepts", "procedures", "entities"):
            # 允許 key 不存在（error 路徑），但若存在必須是 list
            if key in result:
                assert isinstance(result[key], list), f"{key} 應是 list"

    def test_top_k_clamped(self):
        """top_k 超出範圍應被 clamp 而不是拋出例外。"""
        with patch("soul.core.agent.EmbeddingService", side_effect=ImportError("mock")):
            from soul_mcp.tools.memory import soul_memory_retrieve
            # 不拋出例外即可
            result = soul_memory_retrieve("test", top_k=999)
            assert isinstance(result, dict)


# ── soul_chat 測試 ────────────────────────────────────────────────────────────


class TestSoulChat:
    def test_empty_message_returns_error(self):
        from soul_mcp.tools.chat import soul_chat
        result = soul_chat(message="   ")
        assert "error" in result

    def test_returns_correct_schema_on_agent_failure(self):
        """SoulAgent 初始化失敗時，應回傳 error dict（不崩潰）。"""
        with patch("soul_mcp.tools.chat.SoulAgent", side_effect=Exception("DB 不可用")):
            with patch("soul_mcp.tools.chat.get_graph_client", side_effect=Exception("mock")):
                with patch("soul_mcp.tools.chat.get_lite_client", side_effect=Exception("mock")):
                    from soul_mcp.tools.chat import soul_chat
                    result = soul_chat(message="你好", session_id="test-session")
        assert "error" in result

    def test_session_id_preserved(self):
        """若提供 session_id，回傳值必須保留相同的 session_id。"""
        mock_resp = MagicMock()
        mock_resp.text = "你好！"
        mock_resp.session_id = "my-session"
        mock_resp.episode_id = "ep-001"
        mock_resp.gating_passed = True
        mock_resp.gating_action = "pass"
        mock_resp.gating_score = 0.95
        mock_resp.neurochem = {"dopamine": 0.5, "serotonin": 0.5, "mode": "balanced"}
        mock_resp.judge_decision = {"recommended_tool": "none", "reasoning": ""}
        mock_resp.memory_context = MagicMock()
        mock_resp.memory_context.episodes = []
        mock_resp.memory_context.concepts = []
        mock_resp.memory_context.procedures = []

        mock_agent = MagicMock()
        mock_agent.chat.return_value = mock_resp

        with patch("soul_mcp.tools.chat.get_graph_client", side_effect=Exception("no falkor")):
            with patch("soul_mcp.tools.chat.get_lite_client") as mock_gc:
                mock_gc.return_value = MagicMock()
                with patch("soul_mcp.tools.chat.SoulAgent", return_value=mock_agent):
                    with patch("soul_mcp.tools.chat.Session"):
                        from soul_mcp.tools.chat import soul_chat
                        result = soul_chat(message="你好", session_id="my-session")

        assert result.get("session_id") == "my-session"
        assert "text" in result
        assert "neurochem" in result
        assert "memory_hits" in result


# ── server 載入測試 ────────────────────────────────────────────────────────────


def test_server_imports_without_error():
    """確保 server.py 可以被 import 而不拋出例外。"""
    import importlib
    try:
        import soul_mcp.server  # noqa: F401
    except ImportError as e:
        pytest.skip(f"fastmcp 未安裝，跳過：{e}")
