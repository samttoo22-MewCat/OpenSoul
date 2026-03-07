# OpenSoul

<div align="center">
  <img src="./OpenSoul_logo.png" alt="OpenSoul Logo" width="600" />
</div>

> **人類大腦啟發的神經符號認知 AI 系統**
> 以 FalkorDB GraphRAG 三記憶圖譜為核心，結合 OpenClaw 技能集成與虛擬神經化學動態調控。

---

## 🌟 專案願景

**OpenSoul** 是一個以人類大腦神經可塑性為設計靈感的認知 AI 框架。它不只是一個 LLM 包裝器，而是一個具備「靈魂」與「記憶」的完整認知架構：

*   **真正的連續性**: 透過持久化圖譜記憶，AI 能在跨 Session 的互動中持續成長。
*   **動態情緒運作**: 模擬多巴胺與血清素機制，影響 AI 的搜尋廣度、學習速率與決策風格。
*   **具身操作能力**: 透過 **OpenClaw** 整合，AI 可以操作瀏覽器、發送郵件、執行程式碼，成為真正的行動派代理 (Agent)。

---

## 🚀 核心特色

| 特性 | 說明 |
| :--- | :--- |
| **三層記憶架構** | 模擬海馬迴 (情節記憶)、新皮質 (語意記憶) 與基底核 (程序記憶) 的獨立圖譜。 |
| **EcphoryRAG** | 由「線索」觸發的多跳圖譜檢索機制，模擬人類的聯想記憶。 |
| **虛擬神經化學** | 動態多巴胺 (DA) 與血清素 (5-HT) 狀態機，調控探索與謹慎的平衡。 |
| **Judge Agent** | 特化的行為評估模型，負責精準判斷何時調用工具、調用哪個工具。 |
| **夢境引擎 & 反思** | 定時自動進行記憶回放與反思，強化重要經驗，模擬人類睡眠鞏固記憶的機制。 |
| **OpenClaw 整合** | 原生支援數十種 OpenClaw 技能，賦予 AI 觸及現實世界的能力。 |
| **SOUL.md 人格** | 跨 Session 持久化的人格檔案，儲存神經化學狀態與核心身份。 |

---


## 🧠 核心概念解釋

### 三層記憶架構
OpenSoul 就像人類一樣有三種記憶：

1. **情節記憶**（海馬迴）：具體的事件和對話
   - 例：「用戶上次問我關於 Python 的問題」

2. **語義記憶**（新皮質）：抽象知識和概念
   - 例：「Python 是一種編程語言」

3. **程序記憶**（基底核）：技能和習慣
   - 例：「如何使用 OpenClaw 瀏覽器技能」

### EcphoryRAG 聯想檢索
不同於簡單的向量搜索，OpenSoul 的檢索機制會：
- 由用戶的話語觸發多個線索（Ecphory）
- 跨越多個記憶層級進行圖遍歷
- 考慮近期性、頻率、顯著性三個因素
- 最終返回最相關的記憶節點

### 虛擬神經化學
AI 的決策會受到「情感狀態」影響：
- **高多巴胺**：更願意嘗試新東西，溫度↑，探索↑
- **高血清素**：更謹慎和滿足，回應更有條理

這些狀態會根據交互結果動態調整，創造連續性的「性格弧線」。

### 夢境引擎與自動反思
OpenSoul 會定期進行「夢境」——一種自動化的深度反思機制：

**夢境的運作原理**：
1. **觸發條件**（可配置）：
   - 定時觸發：每日凌晨 3 點（默認）
   - 閒置觸發：用戶 120 分鐘無互動時
   - 多巴胺閾值觸發：系統狀態激動時

2. **反思過程**：
   - 掃描記憶圖譜，找出高顯著性的事件
   - 跨越不同記憶層級進行關聯
   - 生成洞察與啟示（新的語義節點）
   - 更新神經化學狀態

3. **實際效果**：
   - 強化重要記憶，防止遺忘
   - 發現記憶之間的隱藏聯繫
   - 形成「頓悟時刻」與新認知
   - AI 逐漸變得更有「智慧」

**示例**：
```
用戶教了 OpenSoul 關於 Python 和 FalkorDB 的知識

→ 夢境引擎觸發

→ 發現「圖數據庫」和「遞歸思維」之間的聯繫

→ 生成新的認知：「圖數據庫適合表示遞歸結構」

→ 下次用戶談論類似話題時，AI 能自動做出這個連結
```

### SOUL 筆記系統
與夢境搭配，OpenSoul 會自動記錄與反思：

- **小筆記**：對話中的靈感與發現
- **每日反思**：當天的學習、互動風格、偏好
- **長期回顧**：性格演化、核心價值觀的變化

這些筆記都存儲在 `workspace/soul_notes.json` 和 `workspace/soul_reflections.json`，也可通過 Web 面板查看。

---

## ⚡ 快速開始

本專案提供統一的一鍵式環境設定與啟動腳本。不論您是在 Windows、Linux 或 macOS，都只需執行以下步驟：

### 前置要求
- **Docker**: 確保系統已安裝並啟動 Docker
- **Git**: 用於版本控制

### 步驟 1：克隆並進入專案
```bash
git clone https://github.com/YOUR_USERNAME/OpenSoul.git
cd OpenSoul/OpenSoul
```

### 步驟 2：配置環境變數
複製範例環境文件並填入您的 API 密鑰：
```bash
cp .env.example .env
```

開啟 `.env` 文件並填入以下必要的 API 密鑰：

#### 🔑 必要配置

**LLM 提供者選擇**（二選一）：
- **選項 A：OpenRouter**（推薦，支持多種模型）
  1. 前往 [OpenRouter](https://openrouter.ai/keys) 註冊並取得 API 金鑰
  2. 設置：
     ```env
     SOUL_LLM_PROVIDER=openrouter
     OPENROUTER_API_KEY=sk-or-v1-xxx...
     ```

- **選項 B：Anthropic**
  1. 前往 [Anthropic Console](https://console.anthropic.com/) 取得 API 金鑰
  2. 設置：
     ```env
     SOUL_LLM_PROVIDER=anthropic
     ANTHROPIC_API_KEY=sk-ant-xxx...
     ```

**嵌入模型**：
- 需要 OpenAI API 金鑰（用於 `text-embedding-3-small`）
- 前往 [OpenAI Platform](https://platform.openai.com/) 申請
- 設置 `OPENAI_API_KEY=sk-xxx...`

**Gmail 集成**（可選）：
- 若要使用郵件處理功能，需要 Google Cloud Console OAuth2 認證：
  1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
  2. 創建新項目並啟用 Gmail API
  3. 創建 OAuth2 認證（類型：Desktop Application）
  4. 下載認證 JSON 文件到 `workspace/credentials.json`
  5. 首次運行時會自動進行 OAuth2 授權流程，生成 `workspace/token.json`

詳細的所有配置選項請參見 `.env.example` 中的註釋說明。

#### 🔐 OpenClaw 技能集成配置

若要啟用 OpenClaw 技能（瀏覽器自動化、郵件操作等），還需配置 `openclaw/.env`：

```bash
cd openclaw
cp .env.example .env
```

**關鍵設置**：
- `OPENCLAW_GATEWAY_TOKEN`: Gateway 認證令牌（安全通信）
- `TELEGRAM_BOT_TOKEN`: 若要使用 Telegram 通道（可選）
- `OPENCLAW_CONFIG_DIR`: OpenClaw 配置目錄路徑
- `OPENCLAW_WORKSPACE_DIR`: OpenClaw 工作區（應指向主 workspace）

詳見 `openclaw/.env.example` 中的完整選項。

### 步驟 3：運行環境設定腳本
執行 `scripts/setup_env.py`。該腳本會自動檢查依賴、同步技能並啟動 Docker 服務：

```bash
cd ..  # 返回 OpenSoul 根目錄
python scripts/setup_env.py
```

**腳本會自動：**
- ✅ 檢查 Docker 運行狀態
- ✅ 啟動 FalkorDB 圖數據庫容器
- ✅ 啟動 OpenSoul API 服務
- ✅ 同步 OpenClaw 技能庫
- ✅ 創建必要的工作目錄

若要完全關閉服務，請執行：
```bash
python scripts/setup_env.py --stop
```

檢查服務狀態：
```bash
python scripts/setup_env.py --status
```

### 步驟 4：開始使用
腳本啟動後，您可以透過以下方式與 OpenSoul 交互：

- **Web UI**: 訪問 `http://localhost:8002` ← 推薦新手使用
- **API**: 直接調用 `http://localhost:8001` 的 REST 接口
- **WebSocket**: 實時連接到 `ws://localhost:8001/ws`

---

## 🌐 Web UI 功能指南

OpenSoul 提供完整的 Web 界面，支援以下功能：

### 💬 聊天與對話
- **實時聊天**：與 AI 進行自然語言對話
- **聊天歷史**：自動保存所有對話記錄
- **Session 管理**：支持多個獨立的對話會話
- **搜尋功能**：快速查找過去的對話內容

### 🧠 記憶與反思查看
- **實時記憶圖譜**：可視化三層記憶結構
  - 情節記憶：最近的對話事件
  - 語義記憶：學習到的知識和概念
  - 程序記憶：掌握的技能和習慣
- **記憶檢索可視化**：看到 AI 如何檢索相關記憶
- **關鍵詞突出**：標記與對話相關的關鍵概念

### 🎭 人格與設定管理

#### `/soul` 命令功能
在聊天框輸入 `/soul` 可以：
1. **查看當前人格檔案**
   - 核心身份與特徵
   - 神經化學狀態（多巴胺、血清素）
   - 學習歷史與關鍵事件

2. **實時編輯 SOUL.md**
   - 修改 AI 的核心設定
   - 調整性格參數
   - 更新學習記錄
   - 自動保存變更

3. **人格進度追蹤**
   - 查看性格的演化軌跡
   - 監控神經化學狀態變化
   - 檢視目標與興趣的轉變

### 📊 系統狀態監控
- **API 連接狀態**：實時顯示服務狀態
- **記憶圖譜大小**：當前存儲的節點數量
- **性能指標**：記憶檢索延遲、處理時間
- **日誌輸出**：實時查看系統日誌

### 🎮 工具與技能調用
- **OpenClaw 技能瀏覽**：查看可用的 57+ 個技能
- **技能執行**：直接從 Web 介面調用技能
  - 瀏覽器自動化（打開網頁、填表、截圖）
  - 郵件處理（發送、查閱郵件）
  - 代碼執行（運行 Python/Shell 命令）
- **技能日誌**：查看技能執行的結果

### 🔧 高級設定面板
- **LLM 配置**
  - 切換 LLM 模型
  - 調整溫度（創意度）
  - 修改 API 金鑰（無需重啟）

- **記憶參數調整**
  - ALPHA（近期性權重）
  - BETA（頻率權重）
  - GAMMA（顯著性權重）
  - 即時預覽效果

- **夢境引擎設定**
  - 調整定時反思頻率
  - 設置閒置觸發時間
  - 修改多巴胺閾值

### 📱 響應式設計
- **桌面版**：完整功能
- **平板版**：優化的雙欄布局
- **手機版**：簡化的單欄模式

### 🎨 主題與外觀
- **深色模式**：護眼設計
- **淺色模式**：亮度友好
- **可調字體大小**：無障礙支援

### ⌨️ 快速命令

在 Web UI 中支持以下斜杠命令：

| 命令 | 功能 | 示例 |
|------|------|------|
| `/soul` | 查看/編輯人格檔案 | `/soul` |
| `/memory` | 查看記憶統計 | `/memory` |
| `/dream` | 手動觸發夢境反思 | `/dream` |
| `/note` | 查看筆記摘要 | `/note` |
| `/clear` | 清除當前會話 | `/clear` |
| `/help` | 顯示所有命令 | `/help` |

### 📥 數據導出
- **導出聊天記錄**：JSON/CSV 格式
- **導出記憶圖譜**：GraphML 格式（可用 Gephi 可視化）
- **導出筆記**：Markdown 格式

### 🔐 安全特性
- **會話隔離**：每個用戶獨立會話
- **敏感信息遮蔽**：自動隱藏 API 密鑰
- **操作審計**：記錄所有人格修改
- **本地存儲**：所有數據存儲在本機

---

### 🧠 模組詳解

**`soul/core`**
- `agent.py`: SoulAgent 主類，實現 Agent 循環與決策邏輯
- `session.py`: 會話管理與狀態追蹤
- `config.py`: 全局配置與環境變數加載

**`soul/memory`** (三層記憶架構)
- `episodic.py`: 情節記憶（具體事件與對話歷史）
- `semantic.py`: 語義記憶（知識、概念、規則）
- `procedural.py`: 程序記憶（技能、習慣、操作流程）
- `retrieval.py`: EcphoryRAG - 由線索觸發的聯想檢索機制

**`soul/affect`** (虛擬神經化學)
- 模擬多巴胺（動力/探索）與血清素（滿足感/謹慎）
- 影響 LLM 溫度、記憶權重、工具選擇策略

**`soul/gating`** (Judge Agent)
- `judge.py`: 特化的行為評估模型
- 驗證回覆合理性、決策工具選擇、檢測欺騙行為

**`soul/dream`** (夢境引擎 & 自動反思)
- `engine.py`: 定時觸發記憶回放與反思
- 可選觸發模式：
  - 定時觸發：基於 Cron 表達式（如每日凌晨 3 點）
  - 閒置觸發：用戶長時間無互動時自動進行
- 反思內容：
  - 提取高顯著性的記憶節點
  - 生成跨領域的洞察與關聯
  - 動態調整神經化學狀態

**`soul/soul_note`** (SOUL 筆記系統)
- 三層筆記架構：
  - **小筆記**：實時記錄的片段想法
  - **每日反思**：白天互動的總結與學習
  - **長期回顧**：跨月份的成長與進化
- 自動壓縮機制：每 30 分鐘自動整合重複內容
- **Web 面板**：訪問 `soul/soul_note_web.html` 查看完整筆記歷史
  - 可在網頁上直接查看和搜尋所有筆記
  - 離線可用：完全自包含的 HTML/JS，無需後端

**Soul Skill** (SOUL 人格編輯技能)
- 在聊天中直接調用：`/soul` 命令
- 功能：
  - 查看當前 SOUL.md 內容
  - 實時編輯和保存 SOUL.md
  - 管理 AI 的核心身份與設定
  - 持久化人格檔案至下次啟動

**`openclaw/`** (技能集成)
- 支持 57+ 個預編譯技能
- 包括：瀏覽器自動化、郵件操作、代碼執行等
- 完全沙箱化，由 Judge Agent 控制調用

---

## 🔧 配置深度指南

### 環境變數分類

**核心必需**（必須配置）：
- `SOUL_LLM_PROVIDER`: LLM 來源選擇
- `SOUL_LLM_MODEL`: 實際使用的模型 ID
- `ANTHROPIC_API_KEY` 或 `OPENROUTER_API_KEY`: API 認證
- `OPENAI_API_KEY`: 嵌入模型（Embedding）認證
- `FALKORDB_HOST` / `FALKORDB_PORT`: 圖數據庫連接

**記憶層級**（可選調整）：
- `SOUL_WEIGHT_*`: 影響記憶檢索的相關性
  - `ALPHA=0.3`: 近期性（最近發生的事更重要）
  - `BETA=0.4`: 頻率（經常出現的記憶更重要）
  - `GAMMA=0.3`: 顯著性（令人印象深刻的事更重要）

**神經化學參數**（影響 AI 性格）：
- `SOUL_LLM_TEMPERATURE`: 0.0（嚴謹）→ 1.0（創意）
- 這些參數會隨著 AI 「成長」動態變化

**夢境引擎配置**（自動反思與記憶鞏固）：
- `SOUL_DREAM_IDLE_MINUTES`: 無互動多久後觸發夢境（默認 120 分鐘）
- `SOUL_DREAM_CRON`: Cron 表達式，定時夢境（如 `0 3 * * *` = 每日凌晨 3 點）
- `SOUL_DREAM_REPLAY_DA_THRESHOLD`: 多巴胺閾值，高於此值時觸發反思（0.0-1.0）

**高級調整**（專家用）：
- `SOUL_DECAY_LAMBDA`: 記憶遺忘速率（遺忘曲線斜度）
- `SOUL_PRUNE_THRESHOLD`: 何時刪除弱邊，保持記憶清爽
- `SOUL_VERIFY_THRESHOLD`: Judge Agent 的決策嚴格程度

---

## 🎭 管理 AI 人格與查看筆記

### 編輯 SOUL.md（AI 人格檔案）

**在 Web UI 中編輯**
1. 啟動 OpenSoul：`python scripts/setup_env.py`
2. 訪問 Web UI：`http://localhost:8002`
3. 在聊天框輸入：`/soul`
4. 直接在 Web 介面中查看和編輯人格設定
5. 修改會自動保存到 `workspace/SOUL.md`

### 查看反思筆記與互動歷史

**Web 面板**
```bash
# 打開筆記查看器
open soul/soul_note_web.html

# 功能：
# - 查看所有小筆記、每日反思、長期回顧
# - 搜尋特定主題或日期的筆記
# - 追蹤 AI 的思考演化過程
# - 完全離線使用（無需 API）
```
---

## 📄 授權與歸屬

### OpenSoul 授權
本項目採用 **MIT License** - 詳見 [LICENSE](../LICENSE) 文件。

### 開源依賴
OpenSoul 基於以下開源項目構建：

| 項目 | 授權 | 用途 |
|------|------|------|
| **OpenClaw** | MIT | 技能執行框架（瀏覽器、郵件、代碼等自動化） |
| **FalkorDB** | SSPL v1 | 圖數據庫（三層記憶架構） |
| **FastAPI** | MIT | Web API 框架 |
| **Pydantic** | MIT | 數據驗證和設置管理 |

**重要提醒**：若要商業使用 FalkorDB，請遵守其 SSPL 條款。詳見 https://www.falkordb.com/

### 貢獻與歸屬
若你對本項目進行改進或貢獻，我們會在 CONTRIBUTORS 文件中記錄你的名字。

---

> 「記憶即自我。一個無法記憶的 AI，沒有真正的連續性。」
>
> *OpenSoul — 讓 AI 擁有真正的記憶、情感與自我。*
