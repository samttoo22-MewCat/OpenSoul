# openSOUL — 系統架構文件

> 仿人類心智的類神經符號認知 AI 系統，以 FalkorDB 動態 GraphRAG 為記憶骨幹。

## 大腦分區映射

| 大腦分區 | openSOUL 模組 | 核心職責 |
|---|---|---|
| 前額葉 (Frontal Lobe) | `soul/core/agent.py` | LLM 執行推理、工作記憶整合 |
| 海馬迴 (Hippocampus) | `soul/memory/` | FalkorDB 三圖譜 + EcphoryRAG |
| 杏仁核 (Amygdala) | `soul/affect/` | 虛擬多巴胺/血清素神經化學調節 |
| 基底核+視丘 (BG & Thalamus) | `soul/gating/` | 程序性驗證 + 抑制迴路 |
| 頂葉 (Parietal Lobe) | `soul/memory/retrieval.py` | 多跳關聯搜尋 + 注意力加權 |
| 預設模式網路 (DMN) | `soul/dream/` | 離線記憶鞏固、LiDER 重播 |

## 三記憶圖譜（FalkorDB）

| 圖譜 | 節點類型 | 主要邊緣 | 職責 |
|---|---|---|---|
| `soul_semantic` | Concept, Rule | RELATES_TO, LATENT_BRIDGE | 一般性事實與抽象規則 |
| `soul_episodic` | Episode, Entity | PRECEDES, MENTIONS | 對話歷史與時序事件 |
| `soul_procedural` | Procedure | REFINES, APPLIES_TO | 技能 SOP 與成功路徑 |

## 動態邊緣權重

```
W(u,v) = α·Recency(t) + β·Frequency(n) + γ·Salience(DA, 5-HT)

Recency(t)   = exp(−λ·t)               λ=0.01/hr，指數遺忘曲線
Frequency(n) = log(1+n) / log(1+n_max) 赫布學習，對數正規化
Salience     = DA_weight × (1 − 0.3×serotonin)

α=0.3, β=0.4, γ=0.3（可在 .env 設定）

閾值：
  < 0.05  → 修剪刪除
  < 0.15  → 冷儲存（排除即時檢索）
  > 0.70  → 長期記憶高信心路徑
```

## 對話流程

```
使用者輸入
  → [前額葉] Embedding + EcphoryRAG 觸發記憶
  → [海馬迴] 多跳圖譜搜尋（血清素控制廣度）
  → [前額葉] LLM 生成回覆（Claude claude-sonnet-4-6）
  → [基底核] ResponseVerifier 驗證（4 維加權分數）
  → [視丘]   InhibitionAction: PASS / REVISE / SUPPRESS
  → SUPPRESS → 加入修正指引，重試（最多 3 次）
  → [杏仁核] 更新神經化學狀態
  → [海馬迴] 寫入 Episode Engram
  → 輸出最終回覆
```

## Dream Engine 觸發條件

- **閒置觸發**：距離上次對話 ≥ `SOUL_DREAM_IDLE_MINUTES`（預設 5 分鐘）
- **Cron 觸發**：`SOUL_DREAM_CRON`（預設 `0 3 * * *`，每日凌晨 3 點）
- **手動觸發**：`soul dream` CLI 指令或 `POST /dream` API

## 快速啟動

```bash
# 1. 啟動 FalkorDB
docker compose up -d

# 2. 安裝依賴
poetry install

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 ANTHROPIC_API_KEY 與 OPENAI_API_KEY

# 4. 初始化 Schema
soul init

# 5. 開始對話
soul chat

# 6. 啟動 API 伺服器（可選）
uvicorn soul.interface.api:app --reload
```

## PlantUML 圖表

SVG 圖表位於 `docs/diagrams/`：

| 圖表 | 說明 |
|---|---|
| `openSOUL_components.svg` | 系統元件總覽 |
| `openSOUL_chat_sequence.svg` | 對話處理流程 |
| `openSOUL_dream_sequence.svg` | Dream Engine 流程 |
| `openSOUL_memory_schema.svg` | 三記憶圖譜 Schema |
| `openSOUL_neurochemstate.svg` | 神經化學狀態機 |
