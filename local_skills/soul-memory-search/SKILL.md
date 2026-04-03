---
name: soul-memory-search
description: 在三個記憶圖譜中搜尋相關內容
---

# 搜尋記憶

執行以下指令以搜尋記憶內容：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli memory search "<查詢詞>"
\`\`\`

## 選項

- `--top-k N` 或 `-k` — 返回最多幾筆結果（預設 5）

## 範例

搜尋相關記憶：
\`\`\`bash
python -m soul.interface.cli memory search "記憶系統" --top-k 10
\`\`\`

搜尋結果包含來自三層記憶的相關節點。
