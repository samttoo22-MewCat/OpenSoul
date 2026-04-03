---
name: soul-clear-db
description: 清空 OpenSoul 記憶資料庫（包括三層記憶圖譜）
---

# 清除資料庫

執行以下指令以清空 OpenSoul 的所有記憶資料庫：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli memory clear
\`\`\`

## 選項

- `--yes` 或 `-y` — 跳過確認提示，直接清空

## 警告

此操作**不可恢復**，將完全清空所有 OpenSoul 資料：
- 三層記憶圖譜（語意、情節、程序）
- 記憶檢索索引
- `daily_logs/` 日誌檔案
- `soul_notes.json` 反思筆記

**唯一保留的部分：**
- `workspace/SOUL.md` 人格檔案（保持）

## 相關指令

- `soul-memory` — 查詢記憶統計
- `soul-dream` — 手動觸發記憶鞏固
