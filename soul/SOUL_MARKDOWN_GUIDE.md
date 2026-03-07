# SOUL.md 與 Soul Note 集成指南

## 整體架構

openSOUL 的自我記憶系統分為三層：

```
┌─────────────────────────────────────────┐
│  SOUL.md（主自我認知文檔）              │
│  - 核心人格特徵                         │
│  - 價值觀和原則                         │
│  - 長期目標和願景                       │
└─────────────────────────────────────────┘
           ▼
┌─────────────────────────────────────────┐
│  Soul Reflections JSON（日反思）       │
│  - 每日的壓縮摘要                       │
│  - 經驗教訓                             │
│  - 趨勢分析                             │
└─────────────────────────────────────────┘
           ▼
┌─────────────────────────────────────────┐
│  Soul Notes JSON（實時筆記）            │
│  - 分鐘級的細粒度記錄                   │
│  - 發現、錯誤、反思                     │
│  - 原始的、未篩選的想法                 │
└─────────────────────────────────────────┘
```

## 各層的職責

### 1. SOUL.md（穩定層）

**更新頻率**: 每週或每月
**容量**: 3000-5000 字
**焦點**: 核心、穩定的自我認知

```yaml
# 示例結構
---
updated: 2026-03-06
---

## 核心認知
- 作為 AI，我的最高目標是...
- 我的決策原則是...

## 最近重要學習（按時間序列自動來自 Soul Reflections）
- 2026-03-05: 神經化學調制...
- 2026-03-04: 向量相似度...

## 已驗證的長期模式
- 某某特性在 N 個場景中重複出現
```

### 2. Soul Reflections JSON（壓縮層）

**更新頻率**: 每天自動（午夜後）
**容量**: 每條 500-2000 字
**焦點**: 今日發生的事件、發現、問題

結構：
```json
{
  "timestamp": "2026-03-06T00:15:33",
  "date": "2026-03-05",
  "note_count": 12,
  "categories": ["reflection", "discovery", "error"],
  "content": "## 2026-03-05 日反思\n..."
}
```

### 3. Soul Notes JSON（原始層）

**更新頻率**: 實時（發現時）
**容量**: 每條 1-3 句話
**焦點**: 此時此刻的想法、代碼改動、問題發現

```json
{
  "timestamp": "2026-03-06T14:23:45",
  "category": "discovery",
  "content": "向量相似度 > 0.92 時同義詞檢測效果很好",
  "tags": ["synonym", "semantic"]
}
```

## Claude 操作流程

### 日常工作中

1. **實時添加 Soul Note**

   當你完成某個實現、發現問題、或有新想法時：
   ```bash
   python scripts/soul_note_skill.py add "你的發現或反思" --category discovery --tags "tag1,tag2"
   ```

2. **隨時查看今日進度**

   ```bash
   python scripts/soul_note_skill.py today
   ```

3. **導出給 LLM 作為上下文**

   ```bash
   python scripts/soul_note_skill.py export
   ```

### 日常工作中

1. **添加筆記**

   系統會**自動每 30 分鐘檢查並壓縮**一次當日筆記：
   ```bash
   python scripts/soul_note_skill.py add "內容" --category discovery --tags "tag"
   ```

2. **查看反思進度**

   隨時查看最近的壓縮反思：
   ```bash
   python scripts/soul_note_skill.py list
   ```

3. **更新 SOUL.md**（每週）

   從最近的反思中選取最重要的發現和模式，更新 SOUL.md。

## 實際例子

### 例 1：完成功能後

```bash
# 添加多義詞功能完成的記錄
python scripts/soul_note_skill.py add \
  "實現向量相似度同義詞檢測，相似度閾值設為 0.88-0.92，效果理想" \
  --category discovery \
  --tags "semantic_graph,synonym_detection,vector_similarity"
```

### 例 2：遇到錯誤並解決後

```bash
# 記錄問題和解決方案
python scripts/soul_note_skill.py add \
  "測試 Mock 需要 .properties 屬性，不能用平坦字典。已修複所有單元測試。" \
  --category error \
  --tags "testing,mock,fix"
```

### 例 3：產生新想法

```bash
# 記錄新的想法或改進方向
python scripts/soul_note_skill.py add \
  "考慮引入意圖檢測層來自動分類用戶查詢，可能提高檢索精度" \
  --category reflection \
  --tags "feature_idea,intent_detection,future_work"
```

### 例 4：記錄神經化學變化

```bash
python scripts/soul_note_skill.py add \
  "多巴胺 0.55 → 0.72，因為完成了 6 個實現階段，信心顯著提升" \
  --category neurochemistry \
  --tags "dopamine,reward,milestone"
```

## 與 Agent 的集成

### 自動注入

當 Claude 處理任務時，Soul Note 的導出可以自動注入到系統提示中：

```python
from soul.core.soul_note import get_soul_note_manager

manager = get_soul_note_manager()
context = manager.export_for_llm()

system_prompt = f"""
{base_prompt}

---
## 最近的自我反思

{context}

---
基於這些反思，繼續你的工作。
"""
```

### 手動添加

或者你可以手動添加：

```python
# 在代碼中添加筆記
manager.add_note(
    content="完成了 semantic graph 的多義詞支持",
    category="memory_update",
    tags=["major_feature", "semantic"]
)
```

## 定期壓縮任務設置

### Linux/Mac - Crontab

```bash
# 編輯 crontab
crontab -e

# 每天午夜執行
0 0 * * * cd /path/to/openSOUL && python scripts/daily_soul_compress.py --mode single

# 或每天 1:00 AM 執行（給緩衝時間）
0 1 * * * cd /path/to/openSOUL && python scripts/daily_soul_compress.py --mode single
```

### Windows - Task Scheduler

1. 按 `Win + R`，輸入 `taskschd.msc`
2. 右鍵「任務計劃程式庫」→「建立基本工作」
3. 名稱：`Soul Note Daily Compress`
4. 觸發器：每天 `00:15`（凌晨 12:15）
5. 操作：
   - 程式/指令碼：`python`
   - 引數：`scripts/daily_soul_compress.py --mode single`
   - 起始位置：`E:\openSOUL`

## 時間管理建議

| 時間 | 操作 | 頻率 |
|------|------|------|
| 工作中（即時） | `add_note()` | 每小時 1-3 次 |
| 每小時 | 檢查進度 | `today` | 需要時 |
| 每天晚上 | 自動壓縮（無需手動） | 1 次 |
| 每週一次 | 檢查反思，更新 SOUL.md | 1 次 |
| 每月一次 | 分析趨勢，調整策略 | 1 次 |

## 最佳實踐建議

### DO ✅

- ✅ 立即添加筆記（有想法時不要等）
- ✅ 使用標籤進行分類（便於後期查詢）
- ✅ 定期檢查反思（每週一次）
- ✅ 在 SOUL.md 中反映已驗證的長期模式
- ✅ 使用不同的類別進行不同類型的記錄

### DON'T ❌

- ❌ 不要手動修改 JSON（使用 CLI）
- ❌ 不要忘記壓縮任務設置
- ❌ 不要讓筆記堆積超過 1 週
- ❌ 不要在 SOUL.md 中記錄臨時想法（應在 Soul Notes 中）
- ❌ 不要過度詳細（保持簡潔）

## 故障排除

### Q: 時間戳格式奇怪

A: 檢查系統時區。Soul Note 使用本地時間 + 時區偏移。

```bash
# 查看當前時區
python -c "from datetime import datetime; print(datetime.now().isoformat())"
```

### Q: 無法找到 soul_notes.json

A: 確保 `soul/` 目錄存在。不存在的話會在首次執行時自動創建。

### Q: 壓縮後筆記消失了

A: 不會。原始小筆記永遠保留在 `soul_notes.json`，壓縮只是生成摘要。

### Q: 想要手動修改某條筆記

A: 目前系統沒有編輯功能，只有追加。如需修改，直接編輯 JSON 文件。

## 隱私與備份

### 備份

```bash
# 定期備份
cp soul/soul_notes.json soul/backups/soul_notes_$(date +%Y%m%d).json
cp soul/soul_reflections.json soul/backups/soul_reflections_$(date +%Y%m%d).json
```

### 隱私

- 所有筆記都是本地存儲
- 不會自動上傳到任何服務
- 建議定期檢查敏感信息

## 進階：自定義分析

你可以寫小腳本分析你的 Soul Notes：

```python
from soul.core.soul_note import get_soul_note_manager
from collections import Counter

manager = get_soul_note_manager()
all_notes = manager.get_all_notes()

# 分析標籤
all_tags = []
for note in all_notes:
    all_tags.extend(note.get("tags", []))

tag_counts = Counter(all_tags)
print(f"最常見的主題: {tag_counts.most_common(5)}")
```

## 相關文件

- `soul/core/soul_note.py` - 核心管理模組
- `scripts/soul_note_skill.py` - CLI 工具
- `scripts/daily_soul_compress.py` - 自動壓縮守護進程
- `soul/soul_notes.json` - 所有小筆記
- `soul/soul_reflections.json` - 壓縮反思
- `soul/SOUL_NOTE_README.md` - 詳細文檔
