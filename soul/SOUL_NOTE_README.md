# Soul Note 系統指南

Soul Note 是一個獨立的自我反思日誌系統，記錄 openSOUL 的思考過程、發現、錯誤和學習。

## 架構

```
soul/
├── soul_notes.json          # 所有小筆記（實時添加）
├── soul_reflections.json    # 日壓縮反思（每晚自動生成）
└── core/soul_note.py        # 管理模組
```

## 筆記層級

### 1. 小筆記（Micro Notes）
- **何時添加**: 實時，每當有新發現、思考、錯誤時
- **時間戳**: 精確到秒的本地時間
- **類別**:
  - `reflection` - 思考反思
  - `discovery` - 新發現
  - `error` - 錯誤排查
  - `memory_update` - 記憶更新
  - `neurochemistry` - 神經化學狀態變化
- **格式**: JSON 列表

### 2. 日反思（Daily Reflections）
- **何時生成**: 每天晚上自動壓縮前一天的所有小筆記
- **結構**:
  - 按類別分組小筆記
  - 生成摘要文本（Markdown 格式）
  - 保留所有原始時間戳
- **用途**: 長期回顧、LLM 上下文、日誌歸檔

### 3. 長期回顧（Long-term Review）
- 保存在 `soul_reflections.json`
- 可用於識別長期趨勢、習慣變化、知識演變

## 使用方式

### 方式 1：直接 CLI

```bash
# 添加反思筆記
python scripts/soul_note_skill.py add "發現向量相似度效果很好" --category discovery --tags "synonym,semantic"

# 添加錯誤筆記
python scripts/soul_note_skill.py add "神經化學調制波動過大，改用梯度下降" --category error --tags "neurochem,fix"

# 添加記憶更新筆記
python scripts/soul_note_skill.py add "語義圖支持多義詞和同義詞檢測" --category memory_update

# 查看今日筆記
python scripts/soul_note_skill.py today

# 壓縮昨日筆記
python scripts/soul_note_skill.py compress

# 壓縮特定日期
python scripts/soul_note_skill.py compress --date 2026-03-05

# 導出供 LLM 使用（列印）
python scripts/soul_note_skill.py export

# 導出到文件
python scripts/soul_note_skill.py export --save /tmp/soul_notes.md

# 列出最近反思
python scripts/soul_note_skill.py list
```

### 方式 2：在 Python 代碼中

```python
from soul.core.soul_note import get_soul_note_manager

manager = get_soul_note_manager()

# 添加筆記
timestamp = manager.add_note(
    content="多義詞顯著性權重更新成功",
    category="memory_update",
    tags=["polysemy", "semantic_graph"]
)

# 獲取今日筆記
today_notes = manager.get_notes_today()

# 按類別篩選
errors = manager.get_notes_by_category("error")

# 導出供 LLM
llm_context = manager.export_for_llm()
```

### 方式 3：定期自動壓縮

#### Linux/Mac - 使用 cron

```bash
# 編輯 crontab
crontab -e

# 添加每天午夜執行的任務
0 0 * * * cd /path/to/openSOUL && python scripts/daily_soul_compress.py --mode single

# 或每天凌晨 1 點執行批量壓縮
0 1 * * * cd /path/to/openSOUL && python scripts/daily_soul_compress.py --mode batch --days 7
```

#### Windows - 使用 Task Scheduler

1. 打開 Task Scheduler
2. 創建新任務
3. 觸發器：每天午夜（0:00）
4. 操作：執行 `python`
5. 參數：`scripts/daily_soul_compress.py --mode single`
6. 起始目錄：`E:\openSOUL`

## JSON 結構

### soul_notes.json

```json
{
  "notes": [
    {
      "timestamp": "2026-03-06T14:23:45+0800",
      "category": "reflection",
      "content": "思考向量相似度閾值的設置...",
      "metadata": {"model": "claude-opus-4-6"},
      "tags": ["semantic", "vector"]
    },
    {
      "timestamp": "2026-03-06T15:10:12+0800",
      "category": "discovery",
      "content": "發現梯度下降式調控比直接加減更穩定",
      "metadata": null,
      "tags": ["neurochem", "improvement"]
    }
  ]
}
```

### soul_reflections.json

```json
{
  "reflections": [
    {
      "timestamp": "2026-03-06T00:15:33+0800",
      "date": "2026-03-05",
      "note_count": 12,
      "categories": ["reflection", "discovery", "memory_update"],
      "content": "## 2026-03-05 日反思\n\n**總筆記數**: 12\n\n### REFLECTION (5)\n...",
      "compressed_from": [
        "2026-03-05T08:30:45+0800",
        "2026-03-05T10:15:22+0800",
        ...
      ]
    }
  ]
}
```

## 與 LLM 集成

Soul Notes 自動被納入 LLM 的上下文：

```python
from soul.core.soul_note import get_soul_note_manager

manager = get_soul_note_manager()
llm_context = manager.export_for_llm()

# 作為系統提示的一部分傳給 LLM
system_prompt = f"""
{base_system_prompt}

---
## 自我反思日誌

{llm_context}
"""
```

## 時間戳格式

所有時間戳都是 ISO 8601 標准，精確到秒，包含本地時區：

```
2026-03-06T14:23:45+0800  # 台灣標准時間
2026-03-06T14:23:45+0000  # UTC
2026-03-06T14:23:45-0500  # 美東時間
```

## 最佳實踐

1. **立即記錄**: 有想法時立即添加筆記，不要等待
2. **使用標籤**: 為每筆筆記添加 1-3 個標籤，便於後期搜索
3. **簡潔內容**: 控制在 1-3 句話，重點突出
4. **定期壓縮**: 最好每天執行壓縮，確保反思的新鮮度
5. **定期檢查**: 每週檢查一次 `soul_reflections.json`，觀察趨勢

## 示例用途

### 追蹤學習進度

```bash
python scripts/soul_note_skill.py export | grep "discovery" # 查看所有發現
```

### 分析決策歷史

```python
manager = get_soul_note_manager()
errors = manager.get_notes_by_category("error")
# 分析哪些決策導致了錯誤
```

### 回溯特定期間

```python
reflections = manager.get_all_reflections()
# 查看特定日期的壓縮反思
```

## 故障排除

### Q: 時間戳顯示錯誤
**A**: 檢查系統時區設置。Soul Note 使用 `datetime.now()` 獲取本地時間。

### Q: 筆記無法添加
**A**: 確保 `soul/soul_notes.json` 文件存在且可寫。運行初始化腳本：
```bash
python -c "from soul.core.soul_note import get_soul_note_manager; get_soul_note_manager()"
```

### Q: 壓縮後筆記還在嗎？
**A**: 是的。壓縮只生成日反思，原始小筆記仍保留在 `soul_notes.json`。

## 隱私與安全

- 所有筆記都以本地 JSON 形式存儲
- 不自動上傳到任何外部服務
- 建議定期備份 `soul_notes.json` 和 `soul_reflections.json`
