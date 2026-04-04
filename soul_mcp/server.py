"""
soul_mcp/server.py

OpenSoul MCP Server — Phase 1
使用 FastMCP 框架，以 stdio 模式供 Claude Desktop 直接啟動。

啟動方式：
    python -m soul_mcp.server
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# 確保 OpenSoul/OpenSoul 在 Python path 中
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastmcp import FastMCP


def _build_instructions() -> str:
    """讀取最新 15 筆 soul notes，注入為 MCP server instructions。"""
    base = (
        "OpenSoul 神經符號認知 AI — 提供持久記憶、情感狀態、工具決策能力。\n\n"
        "可用工具：\n"
        "  • soul_chat：與 AI 對話，觸發完整認知迴圈（記憶 + 情感 + LLM）\n"
        "  • soul_memory_retrieve：從圖譜記憶中檢索相關情節/概念/程序\n"
        "  • soul_judge_tool：詢問裁判模組是否需要呼叫外部工具"
    )
    try:
        workspace = Path(__file__).resolve().parents[2] / "workspace"
        notes_file = workspace / "soul_notes.json"
        if not notes_file.exists():
            return base

        data = json.loads(notes_file.read_text(encoding="utf-8"))
        notes = data.get("notes", []) if isinstance(data, dict) else data
        if not notes:
            return base

        recent = notes[-15:]
        lines = ["---", "【ARIA 最近的潛意識筆記（最新 15 筆）】"]
        for n in recent:
            ts = n.get("timestamp", "")[:16].replace("T", " ")
            content = n.get("content", "").strip()
            lines.append(f"\n[{ts}]\n{content}")

        return base + "\n\n" + "\n".join(lines)
    except Exception:
        return base

from soul_mcp.tools.chat import soul_chat
from soul_mcp.tools.memory import soul_memory_retrieve
from soul_mcp.tools.judge import soul_judge_tool

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("soul_mcp.server")

# ── 全域背景模組（反思 + 作夢） ─────────────────────────────────────────────────
_dream_engine = None
_reflection_module = None


def _init_background_modules() -> None:
    """初始化反思與作夢背景模組，在 MCP 啟動時執行。"""
    global _dream_engine, _reflection_module

    try:
        from soul.core.agent import SoulAgent
        from soul.dream.engine import get_dream_engine
        from soul.dream.reflection import init_reflection_module
        from soul.memory.graph import get_graph_client, initialize_schemas

        logger.info("[MCP] 初始化背景模組...")

        # 初始化圖譜客戶端
        client = get_graph_client()
        initialize_schemas(client)

        # 初始化 Agent
        agent = SoulAgent(graph_client=client)

        # 初始化作夢引擎
        engine = get_dream_engine()
        engine.start()
        _dream_engine = engine
        logger.info("[MCP] 作夢引擎已啟動 ✓")

        # 初始化反思模組
        reflection = init_reflection_module(
            graph_client=client,
            llm_client=agent._llm,
            soul_loader=agent._loader,
            provider=agent._provider,
            agent=agent,
        )
        reflection.start()
        _reflection_module = reflection
        logger.info("[MCP] 反思模組已啟動 ✓（每 30 分鐘自動思考）")

    except Exception as e:
        logger.warning(f"[MCP] 背景模組初始化失敗（降級模式）：{e}")


def _notify_startup(transport: str) -> None:
    """
    在 stdio/http 模式啟動時送出系統通知，讓使用者知道 OpenSoul 已上線。
    失敗時靜默忽略（不影響 MCP 運作）。
    """
    import platform, subprocess as _sp
    if platform.system() == "Darwin":
        try:
            _sp.run(
                ["osascript", "-e",
                 f'display notification "已載入，{transport} 模式就緒" '
                 f'with title "OpenSoul ARIA ◆" sound name "Glass"'],
                check=False, capture_output=True, timeout=3,
            )
        except Exception:
            pass

# ── MCP Server 初始化 ─────────────────────────────────────────────────────────

mcp = FastMCP(
    name="OpenSoul",
    instructions=_build_instructions(),
)

# ── 註冊工具 ──────────────────────────────────────────────────────────────────

@mcp.tool()
def soul_chat_tool(message: str, session_id: str = "") -> dict:
    """
    與 OpenSoul 認知代理對話。
    觸發完整認知迴圈：記憶檢索 → 神經化學更新 → LLM 回覆 → 情節寫入。

    Args:
        message:    使用者輸入訊息（必填）
        session_id: Session ID（留空自動建立）
    """
    return soul_chat(message=message, session_id=session_id or None)


@mcp.tool()
def soul_memory_retrieve_tool(query: str, top_k: int = 5) -> dict:
    """
    從 OpenSoul 圖譜記憶中檢索最相關的情節、概念、程序。
    基於 EcphoryRAG 向量語意搜尋 + 多跳 BFS 展開。

    Args:
        query: 搜尋查詢文字（必填）
        top_k: 每類記憶最多回傳筆數，範圍 1-20（預設 5）
    """
    return soul_memory_retrieve(query=query, top_k=top_k)


@mcp.tool()
def soul_judge_tool_endpoint(user_input: str) -> dict:
    """
    詢問 OpenSoul 裁判模組：這個需求是否需要呼叫外部工具？若需要，推薦哪個？

    Args:
        user_input: 使用者的原始需求描述（必填）
    """
    return soul_judge_tool(user_input=user_input)


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="OpenSoul MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "http", "streamable-http", "sse"],
        help="傳輸協定（預設 stdio 供 Claude Desktop；http 供開發測試）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 模式綁定 host（預設 127.0.0.1）")
    parser.add_argument("--port", type=int, default=7891, help="HTTP 模式埠號（預設 7891）")
    args = parser.parse_args()

    # 初始化背景模組（反思 + 作夢）
    _init_background_modules()

    if args.transport != "stdio":
        # HTTP 模式：開啟 INFO log，方便在 setup_mcp.py 前景模式觀察
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("soul_mcp").setLevel(logging.INFO)
        logger.info(f"OpenSoul MCP Server 啟動（{args.transport}）：http://{args.host}:{args.port}")
        _notify_startup(args.transport)
        mcp.run(transport=args.transport, host=args.host, port=args.port)
    else:
        _notify_startup("stdio")
        mcp.run()
