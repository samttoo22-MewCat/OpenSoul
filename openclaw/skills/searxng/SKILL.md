---
name: searxng
description: 透過自架的 SearXNG 隱私搜尋引擎進行網頁搜尋，聚合 Google、Bing、DuckDuckGo 等多個搜尋來源，不追蹤使用者。適合需要搜尋資訊但不希望洩漏隱私時使用。
homepage: https://github.com/searxng/searxng
metadata:
  {
    "openclaw":
      {
        "emoji": "🔍",
        "requires": {},
        "install": [],
      },
  }
---

# SearXNG 隱私搜尋

自架的隱私保護元搜尋引擎，聚合多個搜尋來源（Google、Bing、DuckDuckGo、Brave 等），不儲存任何搜尋記錄。

## 前置需求

SearXNG 以 Docker 服務方式運行，已整合至 `openclaw/docker-compose.yml`。
確認服務已啟動：

```bash
docker compose -f openclaw/docker-compose.yml up searxng -d
```

服務啟動後可在 `http://localhost:8888` 存取網頁介面。

## 使用時機（觸發情境）

- 搜尋最新資訊、新聞、技術文件
- 需要隱私保護的網頁搜尋
- 從多個搜尋引擎聚合結果
- 搜尋特定類別（新聞、圖片、影片、學術論文等）

## 指令

### 基本搜尋

```bash
python scripts/search.py --query "AI agent security 2025"
```

### 指定類別搜尋

```bash
python scripts/search.py --query "Python asyncio" --categories "it"
python scripts/search.py --query "climate change" --categories "news"
python scripts/search.py --query "machine learning papers" --categories "science"
```

### 指定語言與搜尋引擎數量

```bash
python scripts/search.py --query "台灣 AI 新創" --language "zh-TW" --max-results 10
```

### 輸出格式

```bash
# 預設：精簡摘要（標題 + URL + 摘要）
python scripts/search.py --query "openai news"

# JSON 原始輸出
python scripts/search.py --query "openai news" --json
```

## 可用類別

| 類別 | 說明 |
|------|------|
| `general` | 一般網頁搜尋（預設） |
| `news` | 新聞 |
| `it` | 技術/IT |
| `science` | 學術論文 |
| `images` | 圖片 |
| `videos` | 影片 |
| `social media` | 社群媒體 |

## 注意事項

- SearXNG 服務需在 Docker 內運行（`http://searxng:8888` 容器內部，`http://localhost:8888` 主機存取）
- 搜尋結果品質取決於各搜尋引擎的回應，可能偶有空結果
- 無 API 金鑰需求，完全本地運行
