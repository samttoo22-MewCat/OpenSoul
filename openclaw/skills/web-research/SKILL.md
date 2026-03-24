---
name: web-research
description: 整合 SearXNG 隱私搜尋與 Jina Reader 頁面抓取的輕量網頁研究工具。可搜尋網路資訊（search）、抓取單一網頁的乾淨 Markdown 內容（fetch）、或一次完成搜尋+自動抓取前幾筆結果全文（research）。無需啟動瀏覽器，速度快、無追蹤。需要上網查資料時優先使用此工具。
homepage: https://docs.jina.ai/
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": {},
        "install": [],
      },
  }
---

# Web Research（SearXNG + Jina Reader）

輕量網頁研究工具，結合兩個元件：

| 元件 | 用途 | 端點 |
|------|------|------|
| **SearXNG**（本地） | 隱私搜尋，聚合 Google / Bing / DDG 等 | `http://localhost:8888` |
| **Jina Reader** | 將任意 URL 轉成乾淨 Markdown，無須瀏覽器 | `https://r.jina.ai/<url>` |

## 何時使用

- 需要搜尋最新資訊、新聞、技術文件 → 用 `research` 或 `search`
- 需要讀取某個網頁的全文內容 → 用 `fetch`
- **優先選擇此工具**取代 `browser-control`；只有在需要登入、互動操作或 JS 渲染時才改用瀏覽器

## 前置需求

SearXNG 須在 Docker 內運行：

```bash
docker compose -f openclaw/docker-compose.yml up searxng -d
```

Jina Reader 為雲端服務，不需額外設定。

---

## 指令

### 1. 搜尋（search）

```bash
python scripts/web_research.py --action search --query "Claude AI 2025"
python scripts/web_research.py --action search --query "台灣 AI 新創" --language "zh-TW" --max-results 10
python scripts/web_research.py --action search --query "Python asyncio" --categories "it"
python scripts/web_research.py --action search --query "openai" --json
```

### 2. 抓取單頁（fetch）

```bash
python scripts/web_research.py --action fetch --url "https://example.com"
python scripts/web_research.py --action fetch --url "https://news.ycombinator.com" --timeout 20
python scripts/web_research.py --action fetch --url "https://example.com" --json
```

### 3. 搜尋 + 自動抓取全文（research）

```bash
# 搜尋並抓取前 3 筆結果全文（預設）
python scripts/web_research.py --action research --query "AI agent security 2025"

# 抓取前 5 筆
python scripts/web_research.py --action research --query "LangChain tutorial" --fetch-top 5

# 中文搜尋
python scripts/web_research.py --action research --query "生成式 AI 應用" --language "zh-TW" --fetch-top 2
```

---

## 參數一覽

| 參數 | 預設 | 說明 |
|------|------|------|
| `--action` | 必填 | `search` / `fetch` / `research` |
| `--query` / `-q` | — | 搜尋關鍵字 |
| `--url` / `-u` | — | 目標 URL（fetch 用） |
| `--categories` / `-c` | `general` | `general, news, it, science, images, videos, social media` |
| `--language` / `-l` | `en-US` | 語言代碼 |
| `--max-results` / `-n` | `5` | 搜尋結果數量上限 |
| `--fetch-top` | `3` | research 模式抓取前幾筆完整內容 |
| `--timeout` | `15` | Jina Reader 逾時秒數 |
| `--json` | off | 輸出原始 JSON |

---

## 與其他 skill 的關係

- **searxng**：本 skill 已包含其功能，獨立使用 `searxng` skill 仍可進行純搜尋
- **browser-control**：本 skill 可取代其 `fetch` 動作；登入、點擊、截圖等互動操作仍需 `browser-control`
