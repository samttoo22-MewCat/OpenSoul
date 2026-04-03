---
name: soul-notes-list
description: 列出最近的反思筆記統計，包含「反思」與「作夢」標記
---

# 反思筆記統計

執行以下指令以列出最近的反思筆記：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli notes list
\`\`\`

## 功能

- 顯示所有反思筆記與小筆記統計
- 按類別分析筆記分佈
- 自動檢測 💭 反思 與 💤 作夢 標記
- 顯示最近的反思內容

## 選項

- `--limit N` 或 `-n` — 顯示最近 N 篇反思（預設 10）

## 範例

顯示最近 20 篇反思：
\`\`\`bash
python -m soul.interface.cli notes list --limit 20
\`\`\`
