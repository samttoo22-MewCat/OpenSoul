"""
soul/core/session.py

Session 管理：對話 Session 生命週期與每日日誌寫入。
對應設計模式：OpenClaw 的 memory/YYYY-MM-DD.md 每日日誌機制
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from soul.core.config import settings


class Session:
    """對話 Session 管理器。"""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.started_at = datetime.now(UTC)
        self._log_entries: list[str] = []
        self.turn_count: int = 0                    # 對話輪數（每次 chat() 加 1）
        self.last_episode_id: str | None = None     # 最後寫入的 Episode ID

    def log(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """記錄一條對話條目（user / assistant / system）。"""
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        entry = f"[{ts}] **{role}**: {content}"
        if metadata:
            extra = ", ".join(f"{k}={v}" for k, v in metadata.items())
            entry += f"\n  > {extra}"
        self._log_entries.append(entry)

    def flush_to_daily_log(self) -> Path:
        """將本 Session 的對話日誌追加寫入今日日誌檔案。"""
        log_dir = settings.daily_log_dir
        log_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        log_path = log_dir / f"{today}.md"

        header = (
            f"\n\n## Session {self.session_id[:8]}"
            f" — {self.started_at.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        )

        content = header + "\n".join(self._log_entries) + "\n"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(content)

        return log_path

    def summary(self) -> str:
        """生成本 Session 的簡短摘要（用於寫入情節記憶）。"""
        if not self._log_entries:
            return ""
        # 取前後各 2 條交互作為摘要
        entries = self._log_entries
        if len(entries) <= 4:
            return " | ".join(entries)
        return " | ".join(entries[:2]) + " ... " + " | ".join(entries[-2:])
