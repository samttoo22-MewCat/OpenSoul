---
name: soul-memory
description: 查詢記憶圖譜統計，顯示情節、語意、程序三層記憶的節點和邊數
---

# 記憶統計

執行以下指令以查詢記憶圖譜統計：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli memory stats
\`\`\`

## 功能

顯示三個記憶圖譜的詳細統計：
- **語意記憶**（soul_semantic）— 概念和知識連結
- **情節記憶**（soul_episodic）— 經歷和事件，包含待重播次數
- **程序性記憶**（soul_procedural）— 技能和程序

## 相關指令

- `soul-memory-search` — 搜尋特定記憶內容
- `soul-dream` — 手動觸發記憶鞏固
