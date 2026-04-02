"""
soul_mcp/adapters/neurochem_adapter.py

從 workspace/SOUL.md 讀取 / 寫入神經化學狀態的輕量介面。
直接複用 soul.affect.neurochem.NeurochemState.to_dict() / from_dict()，
不依賴 FalkorDB。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter


def _soul_md_path() -> Path:
    """從 config 取得 SOUL.md 路徑，找不到則回退至相對路徑。"""
    try:
        from soul.core.config import settings
        return settings.soul_md_path
    except Exception:
        return Path("workspace/SOUL.md")


def load_neurochem() -> "NeurochemState":
    """
    從 SOUL.md frontmatter 載入 NeurochemState。
    若檔案不存在或解析失敗，回傳預設平衡狀態。
    """
    from soul.affect.neurochem import NeurochemState

    path = _soul_md_path()
    if not path.exists():
        return NeurochemState()

    try:
        post = frontmatter.load(str(path))
        meta: dict = dict(post.metadata)
        neuro_data = meta.get("neurochem", meta)
        return NeurochemState.from_dict(neuro_data)
    except Exception:
        return NeurochemState()


def save_neurochem(state: "NeurochemState") -> None:
    """
    將 NeurochemState 寫回 SOUL.md frontmatter。
    若檔案不存在則靜默忽略。
    """
    path = _soul_md_path()
    if not path.exists():
        return

    try:
        post = frontmatter.load(str(path))
        post.metadata["neurochem"] = state.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))
    except Exception:
        pass


def get_neurochem_snapshot() -> dict[str, Any]:
    """取得神經化學狀態快照（dict），供 MCP tool 回傳使用。"""
    state = load_neurochem()
    return state.to_dict()
