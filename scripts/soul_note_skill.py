#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/soul_note_skill.py

Soul Note 管理 CLI 工具 - 供 Claude Code Skill 調用。

用法：
  python soul_note_skill.py add "反思內容" [--category reflection] [--tags tag1,tag2]
  python soul_note_skill.py today         # 顯示今日筆記
  python soul_note_skill.py compress     # 壓縮昨日筆記
  python soul_note_skill.py export       # 導出供 LLM 使用
"""

import sys
import argparse
import json
import io
from pathlib import Path
from datetime import datetime

# 強制 UTF-8 輸出（解決 Windows 控制台編碼問題）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 加入 openSOUL 到路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from soul.core.soul_note import get_soul_note_manager


def cmd_add(args):
    """添加新筆記。"""
    manager = get_soul_note_manager()

    tags = []
    if args.tags:
        tags = [tag.strip() for tag in args.tags.split(",")]

    timestamp = manager.add_note(
        content=args.content,
        category=args.category,
        tags=tags,
    )

    print(f"✅ 筆記已添加: {timestamp}")
    print(f"   類別: {args.category}")
    print(f"   內容: {args.content}")
    if tags:
        print(f"   標籤: {', '.join(tags)}")


def cmd_today(args):
    """顯示今日筆記。"""
    manager = get_soul_note_manager()
    notes = manager.get_notes_today()

    if not notes:
        print("📝 今日暫無筆記")
        return

    print(f"📝 今日筆記（{len(notes)} 條）\n")
    for note in notes:
        time_part = note["timestamp"].split("T")[1][:8]  # HH:MM:SS
        print(f"[{time_part}] {note['category'].upper()}")
        print(f"  {note['content']}")
        if note.get("tags"):
            tags_str = " ".join(f"#{tag}" for tag in note["tags"])
            print(f"  {tags_str}")
        print()


def cmd_compress(args):
    """壓縮指定日期的筆記。"""
    manager = get_soul_note_manager()

    target_date = args.date if args.date else None
    timestamp = manager.compress_daily_reflection(target_date)

    if timestamp:
        print(f"✅ 日反思已壓縮: {timestamp}")
        if target_date:
            print(f"   日期: {target_date}")
    else:
        print("⚠️  沒有找到要壓縮的筆記")


def cmd_export(args):
    """導出供 LLM 使用。"""
    manager = get_soul_note_manager()
    output = manager.export_for_llm()

    if args.save:
        save_path = Path(args.save)
        save_path.write_text(output, encoding="utf-8")
        print(f"✅ 已導出到: {save_path}")
    else:
        print(output)


def cmd_list(args):
    """列出最近的反思。"""
    manager = get_soul_note_manager()
    reflections = manager.get_all_reflections()

    if not reflections:
        print("📋 暫無反思記錄")
        return

    print(f"📋 最近的 {min(5, len(reflections))} 條反思\n")
    for ref in reflections[-5:]:
        print(f"📅 {ref['date']} ({ref['note_count']} 筆)")
        print(f"   類別: {', '.join(ref['categories'])}")
        print(f"   時間: {ref['timestamp']}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Soul Note 管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # add 命令
    add_parser = subparsers.add_parser("add", help="添加新筆記")
    add_parser.add_argument("content", help="筆記內容")
    add_parser.add_argument(
        "--category",
        default="reflection",
        choices=["reflection", "discovery", "error", "memory_update", "neurochemistry"],
        help="筆記類別",
    )
    add_parser.add_argument("--tags", help="標籤（逗號分隔，如 'tag1,tag2'）")
    add_parser.set_defaults(func=cmd_add)

    # today 命令
    today_parser = subparsers.add_parser("today", help="顯示今日筆記")
    today_parser.set_defaults(func=cmd_today)

    # compress 命令
    compress_parser = subparsers.add_parser("compress", help="壓縮日筆記")
    compress_parser.add_argument(
        "--date",
        help="目標日期 (YYYY-MM-DD)，不指定則為昨天",
    )
    compress_parser.set_defaults(func=cmd_compress)

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出反思")
    list_parser.set_defaults(func=cmd_list)

    # export 命令
    export_parser = subparsers.add_parser("export", help="導出筆記")
    export_parser.add_argument(
        "--save",
        help="保存到文件（不指定則列印）",
    )
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        args.func(args)
        return 0
    except Exception as e:
        print(f"❌ 錯誤: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
