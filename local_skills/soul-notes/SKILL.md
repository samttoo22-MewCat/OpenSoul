---
name: soul-notes
description: 查看今日或指定日期的反思筆記與小筆記
---

# 查看反思筆記

執行以下指令以查看反思筆記：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli notes view
\`\`\`

## 選項

- `--date YYYY-MM-DD` 或 `-d` — 查看指定日期的筆記
- `--category TYPE` 或 `-c` — 按類別篩選（reflection/discovery/error/memory_update）

## 範例

查看 2026-04-02 的反思筆記：
\`\`\`bash
python -m soul.interface.cli notes view --date 2026-04-02
\`\`\`

只顯示 reflection 類別：
\`\`\`bash
python -m soul.interface.cli notes view --category reflection
\`\`\`
