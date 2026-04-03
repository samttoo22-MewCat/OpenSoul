---
name: soul-dream
description: 手動觸發夢境鞏固引擎，執行記憶整合和圖譜優化
---

# 夢境鞏固

執行以下指令以手動觸發夢境引擎：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli dream
\`\`\`

## 功能

夢境引擎執行三個主要操作：
1. **經驗重播** — 重新處理高價值的未重播情節
2. **知識蒸餾** — 從情節提取新概念到語意記憶
3. **圖譜修剪** — 移除弱邊並建立知識捷徑

## 選項

- `--replay-only` — 僅執行經驗重播，跳過其他步驟

## 相關指令

- `soul-notes-list` — 檢視記憶中的反思和作夢標記
- `soul-memory` — 查看記憶統計
