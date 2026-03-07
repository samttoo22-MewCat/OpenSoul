"""
soul/core/soul_note.py

Soul Note 管理系統 - 獨立的自我反思日誌。

特性：
  - 精確到秒的本地時間戳
  - 自動每 30 分鐘壓縮與整理（系統內部實現）
  - JSON 存儲，易於查詢與分析
  - 支援三層結構：小筆記 → 日反思 → 長期回顧
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("soul.soul_note")


@dataclass
class SoulNote:
    """單條靈魂筆記。"""

    timestamp: str  # ISO 8601 with local time
    category: str  # "reflection", "discovery", "error", "memory_update", "neurochemistry"
    content: str
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SoulNoteManager:
    """Soul Note 管理器。"""

    def __init__(self, soul_dir: Path = Path("E:/openSOUL/soul")):
        self.soul_dir = Path(soul_dir)
        self.notes_file = self.soul_dir / "soul_notes.json"
        self.reflections_file = self.soul_dir / "soul_reflections.json"

        # 自動壓縮配置
        self.auto_compress_interval = 1800  # 30 分鐘（秒）
        self.last_auto_compress_time = 0  # Unix 時間戳

        # 確保文件存在
        self._ensure_files_exist()

    def _ensure_files_exist(self) -> None:
        """確保 JSON 文件存在且格式有效。"""
        if not self.notes_file.exists() or self.notes_file.stat().st_size == 0:
            self.notes_file.parent.mkdir(parents=True, exist_ok=True)
            self.notes_file.write_text(json.dumps({"notes": []}, indent=2, ensure_ascii=False))
        else:
            try:
                json.loads(self.notes_file.read_text(encoding="utf-8"))
            except ValueError:
                self.notes_file.write_text(json.dumps({"notes": []}, indent=2, ensure_ascii=False))

        if not self.reflections_file.exists() or self.reflections_file.stat().st_size == 0:
            self.reflections_file.parent.mkdir(parents=True, exist_ok=True)
            self.reflections_file.write_text(json.dumps({"reflections": []}, indent=2, ensure_ascii=False))
        else:
            try:
                json.loads(self.reflections_file.read_text(encoding="utf-8"))
            except ValueError:
                self.reflections_file.write_text(json.dumps({"reflections": []}, indent=2, ensure_ascii=False))

    def _get_local_timestamp(self) -> str:
        """取得精確到秒的本地時間戳（ISO 8601）。"""
        now = datetime.now()
        # Format: YYYY-MM-DDTHH:MM:SS+08:00 (或當地時區)
        return now.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _check_auto_compress(self) -> None:
        """
        檢查是否需要自動壓縮。
        每 30 分鐘檢查一次，若有新筆記則壓縮。
        """
        import time

        current_time = time.time()

        # 檢查是否超過 30 分鐘間隔
        if current_time - self.last_auto_compress_time < self.auto_compress_interval:
            return

        # 更新最後壓縮時間
        self.last_auto_compress_time = current_time

        # 檢查今天是否有新筆記
        today = datetime.now().strftime("%Y-%m-%d")
        today_notes = self.get_notes_today()

        if today_notes:
            # 自動壓縮今日筆記
            try:
                self.compress_daily_reflection(today, merge_existing=True)
            except Exception as e:
                # 靜默失敗，不影響筆記添加
                pass

    def add_note(
        self,
        content: str,
        category: str = "reflection",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """
        添加一條小筆記。

        Args:
            content: 筆記內容
            category: 筆記類別 (reflection, discovery, error, memory_update, neurochemistry)
            metadata: 額外元數據
            tags: 標籤列表

        Returns:
            筆記的 timestamp
        """
        timestamp = self._get_local_timestamp()

        note = SoulNote(
            timestamp=timestamp,
            category=category,
            content=content,
            metadata=metadata or {},
            tags=tags or [],
        )

        logger.info(f"[SoulNote] 創建新筆記 ({category}): {content[:30]}...")

        # 讀取現有筆記
        notes_data = json.loads(self.notes_file.read_text(encoding="utf-8"))
        notes_data["notes"].append(note.to_dict())

        # 寫回
        self.notes_file.write_text(
            json.dumps(notes_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # 🆕 添加後自動檢查是否需要壓縮
        self._check_auto_compress()

        return timestamp

    def get_notes_today(self) -> list[dict]:
        """獲取今日的所有筆記。"""
        notes_data = json.loads(self.notes_file.read_text(encoding="utf-8"))

        today = datetime.now().strftime("%Y-%m-%d")
        today_notes = [
            note for note in notes_data["notes"]
            if note["timestamp"].startswith(today)
        ]

        return today_notes

    def get_notes_by_category(self, category: str) -> list[dict]:
        """按類別獲取筆記。"""
        notes_data = json.loads(self.notes_file.read_text(encoding="utf-8"))
        return [note for note in notes_data["notes"] if note["category"] == category]

    def compress_daily_reflection(self, target_date: Optional[str] = None, merge_existing: bool = True, custom_content: Optional[str] = None) -> str:
        """
        壓縮整理指定日期的所有筆記為一條長反思筆記。
        若該日期已有反思，則與新筆記合併生成更新版本。

        Args:
            target_date: 目標日期 (YYYY-MM-DD)，不指定則為昨天
            merge_existing: 是否合併已有的反思與新筆記（預設 True）
            custom_content: 若提供，則使用此自定義內容（例如 LLM 產生的深度摘要）而非預設拼接。

        Returns:
            生成的反思筆記的 timestamp
        """
        if not target_date:
            # 預設壓縮昨天的筆記
            target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        notes_data = json.loads(self.notes_file.read_text(encoding="utf-8"))
        reflections_data = json.loads(self.reflections_file.read_text(encoding="utf-8"))

        # 篩選該日期的小筆記
        day_notes = [
            note for note in notes_data["notes"]
            if note["timestamp"].startswith(target_date)
        ]

        if not day_notes and not custom_content:
            return ""  # 沒有筆記可壓縮且無自定義內容

        # 檢查該日期是否已有反思
        existing_reflection = None
        if merge_existing:
            for ref in reflections_data["reflections"]:
                if ref["date"] == target_date:
                    existing_reflection = ref
                    break

        # 按類別分組 (無論是否使用 custom_content 都需要此資訊作為元數據)
        by_category = {}
        for note in day_notes:
            cat = note["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(note)

        if custom_content:
            compressed_content = custom_content
        else:
            # 生成新的壓縮摘要 (預設拼接)
            # 構建新摘要
            summary_parts = [f"## {target_date} 日反思\n"]

            if existing_reflection:
                summary_parts.append(f"**最後更新**: {self._get_local_timestamp()}\n")
                summary_parts.append(f"**版本**: {existing_reflection.get('version', 1) + 1}\n")
                summary_parts.append(f"**累積筆記數**: {len(day_notes) + existing_reflection.get('original_note_count', 0)}\n\n")

                # 添加舊反思的關鍵部分（保留上一版本的要點）
                if existing_reflection.get("key_insights"):
                    summary_parts.append("### 之前的關鍵要點\n")
                    for insight in existing_reflection["key_insights"]:
                        summary_parts.append(f"- {insight}\n")
                    summary_parts.append("\n")
            else:
                summary_parts.append(f"**總筆記數**: {len(day_notes)}\n")

            # 新筆記按類別分組
            for category, notes in sorted(by_category.items()):
                summary_parts.append(f"\n### {category.upper()} ({len(notes)})\n")
                for note in notes:
                    time_part = note["timestamp"].split("T")[1]  # HH:MM:SS
                    summary_parts.append(f"- **{time_part}**: {note['content']}\n")

                    if note.get("tags"):
                        tags_str = " ".join(f"#{tag}" for tag in note["tags"])
                        summary_parts.append(f"  Tags: {tags_str}\n")

            compressed_content = "".join(summary_parts)

        logger.info(f"[SoulNote] 壓縮 {target_date} 筆記，共 {len(day_notes)} 筆")

        # 提取關鍵要點（用於下次合併時保留）
        key_insights = [
            note["content"]
            for note in day_notes
            if note["category"] in ["discovery", "memory_update"]
        ][:5]  # 最多保留 5 個要點

        # 生成或更新反思
        reflection_timestamp = self._get_local_timestamp()

        if existing_reflection:
            # 更新現有反思（替換為新版本）
            reflection_entry = {
                "timestamp": reflection_timestamp,
                "date": target_date,
                "version": existing_reflection.get("version", 1) + 1,
                "note_count": len(day_notes),
                "original_note_count": existing_reflection.get("original_note_count", existing_reflection.get("note_count", 0)) + len(day_notes),
                "categories": list(by_category.keys()),
                "key_insights": key_insights,
                "content": compressed_content,
                "compressed_from": [note["timestamp"] for note in day_notes],
                "previous_version_timestamp": existing_reflection["timestamp"],
            }

            # 替換舊反思
            reflections_data["reflections"] = [
                ref for ref in reflections_data["reflections"]
                if ref["date"] != target_date
            ]
            reflections_data["reflections"].append(reflection_entry)
        else:
            # 創建新反思
            reflection_entry = {
                "timestamp": reflection_timestamp,
                "date": target_date,
                "version": 1,
                "note_count": len(day_notes),
                "original_note_count": len(day_notes),
                "categories": list(by_category.keys()),
                "key_insights": key_insights,
                "content": compressed_content,
                "compressed_from": [note["timestamp"] for note in day_notes],
            }

            reflections_data["reflections"].append(reflection_entry)

        self.reflections_file.write_text(
            json.dumps(reflections_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        return reflection_timestamp

    def clear_all(self) -> None:
        """清空所有筆記與反思，重置為預設空狀態。"""
        self.notes_file.write_text(json.dumps({"notes": []}, indent=2, ensure_ascii=False), encoding="utf-8")
        self.reflections_file.write_text(json.dumps({"reflections": []}, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.warning("[SoulNote] 所有筆記與反思已清空")

    def get_all_notes(self) -> list[dict]:
        """取得所有筆記。"""
        try:
            content = self.notes_file.read_text(encoding="utf-8").strip()
            if not content: return []
            return json.loads(content).get("notes", [])
        except Exception as e:
            logger.error(f"[SoulNote] 讀取筆記失敗: {e}")
            return []

    def get_all_reflections(self) -> list[dict]:
        """取得所有日反思。"""
        try:
            content = self.reflections_file.read_text(encoding="utf-8").strip()
            if not content: return []
            return json.loads(content).get("reflections", [])
        except Exception as e:
            logger.error(f"[SoulNote] 讀取反思失敗: {e}")
            return []

    def export_for_llm(self) -> str:
        """
        導出所有 Soul Note 與反思，供 LLM 使用。

        Returns:
            格式化的文本，包含最近的反思與筆記
        """
        reflections = self.get_all_reflections()
        notes = self.get_notes_today()

        output_lines = ["# SOUL NOTES FOR LLM CONTEXT\n"]

        # 最近的反思（最後5條）
        if reflections:
            output_lines.append("## 最近日反思\n")
            for ref in reflections[-5:]:
                output_lines.append(f"### {ref['date']}\n")
                output_lines.append(ref["content"])
                output_lines.append("\n")

        # 今日筆記（若有）
        if notes:
            output_lines.append("## 今日筆記（未壓縮）\n")
            for note in notes:
                output_lines.append(f"- [{note['timestamp']}] **{note['category']}**: {note['content']}\n")

        return "".join(output_lines)


# 全局實例
_manager: Optional[SoulNoteManager] = None


def get_soul_note_manager() -> SoulNoteManager:
    """取得全局 Soul Note 管理器實例。"""
    global _manager
    if _manager is None:
        _manager = SoulNoteManager()
    return _manager
