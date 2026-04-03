---
name: soul-edit
description: 使用 diff 精確修改 SOUL.md 人格檔案的指定片段，避免覆蓋整個檔案
---

# 編輯 SOUL.md（Diff 模式）

**優先使用 diff 指令**——只替換指定的舊文字片段，不重寫整個檔案。

## Diff 模式（精確修改，推薦）

```bash
cd /Users/mac/Desktop/coding/py/OpenSoul/OpenSoul
python scripts/edit_soul_skill.py --command diff \
  --old "要被替換的舊文字（需與 SOUL.md 完全一致）" \
  --new "替換後的新文字"
```

**注意事項：**
- `--old` 必須與 SOUL.md 現有內容**完全一致**（含空白、換行符）
- `--old` 在檔案中必須唯一，若不唯一請提供更多上下文
- 修改前先執行 `read` 確認當前內容

## 讀取當前內容

```bash
python scripts/edit_soul_skill.py --command read
```

## Append 模式（在末尾新增）

```bash
python scripts/edit_soul_skill.py --command append --text "新增的內容"
```

## Replace 模式（整體替換，謹慎使用）

```bash
python scripts/edit_soul_skill.py --command replace --text "完整的新內容"
```

## 使用流程

1. 先 `read` 確認當前 SOUL.md 內容
2. 找出要修改的精確片段
3. 用 `diff` 指令替換，提供完整的 `--old` 與 `--new`
4. 再次 `read` 確認修改結果
