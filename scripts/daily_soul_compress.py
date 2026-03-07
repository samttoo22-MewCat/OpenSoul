#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/daily_soul_compress.py

每日自動壓縮 Soul Note 的守護腳本。

可以：
  1. 直接運行：python daily_soul_compress.py
  2. 作為 cron job 定期執行（Linux/Mac）
  3. 作為 Windows Task Scheduler 任務
"""

import sys
import logging
import io
from pathlib import Path
from datetime import datetime, timedelta

# 強制 UTF-8 輸出（解決 Windows 控制台編碼問題）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 加入 openSOUL 到路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from soul.core.soul_note import get_soul_note_manager

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def compress_previous_day():
    """壓縮前一天的筆記（通常在午夜後執行）。"""
    manager = get_soul_note_manager()

    # 計算前一天的日期
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # 檢查前一天是否有筆記
        notes_data = manager.get_all_notes()
        yesterday_notes = [n for n in notes_data if n["timestamp"].startswith(yesterday)]

        if not yesterday_notes:
            logger.info(f"📝 {yesterday} 沒有筆記，跳過壓縮")
            return False

        reflections = manager.get_all_reflections()
        existing = any(r["date"] == yesterday for r in reflections)

        if existing:
            logger.info(f"🔄 正在重新壓縮 {yesterday} 的 {len(yesterday_notes)} 筆筆記...")
            logger.info(f"   （該日期已有反思，將合併新筆記生成更新版本）")
        else:
            logger.info(f"🔄 正在壓縮 {yesterday} 的 {len(yesterday_notes)} 筆筆記...")

        timestamp = manager.compress_daily_reflection(yesterday, merge_existing=True)

        if timestamp:
            if existing:
                logger.info(f"✅ 反思已更新: {timestamp}")
            else:
                logger.info(f"✅ 壓縮完成: {timestamp}")
            return True
        else:
            logger.warning(f"⚠️  壓縮失敗")
            return False

    except Exception as e:
        logger.error(f"❌ 錯誤: {e}", exc_info=True)
        return False


def compress_multiple_days(days_back: int = 7):
    """
    壓縮過去 N 天內未壓縮的筆記。

    Args:
        days_back: 回溯天數（預設7天）
    """
    manager = get_soul_note_manager()
    reflections = manager.get_all_reflections()

    # 已壓縮的日期集合
    compressed_dates = {ref["date"] for ref in reflections}

    logger.info(f"🔍 檢查過去 {days_back} 天內未壓縮的筆記...")

    success_count = 0
    for i in range(days_back, 0, -1):
        target_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")

        if target_date in compressed_dates:
            logger.debug(f"  ⏭️  {target_date} 已壓縮，跳過")
            continue

        # 檢查是否有筆記
        notes = manager.get_all_notes()
        day_notes = [n for n in notes if n["timestamp"].startswith(target_date)]

        if not day_notes:
            logger.debug(f"  ⏭️  {target_date} 沒有筆記")
            continue

        logger.info(f"  🔄 壓縮 {target_date} ({len(day_notes)} 筆)...")
        timestamp = manager.compress_daily_reflection(target_date)

        if timestamp:
            success_count += 1
            logger.info(f"  ✅ 成功")

    logger.info(f"\n📊 批量壓縮完成: {success_count} 天")
    return success_count > 0


def main():
    """主函數。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Soul Note 每日壓縮工具",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "batch"],
        default="single",
        help="壓縮模式 (single=前一天, batch=過去7天)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="回溯天數（用於 batch 模式）",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Soul Note 每日壓縮")
    logger.info("=" * 60)

    if args.mode == "single":
        compress_previous_day()
    else:
        compress_multiple_days(args.days)

    logger.info("\n✅ 完成\n")


if __name__ == "__main__":
    main()
