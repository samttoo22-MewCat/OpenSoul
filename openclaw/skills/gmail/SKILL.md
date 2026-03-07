---
name: gmail
description: 透過 Google OAuth2 API 讀取 Gmail 信件。可用於檢索最近信件、提取郵件內容、自動標記為已讀。支援多語言編碼與自動快取。
---

# Gmail Integration (OAuth2 API)

此技能允許透過 Google OAuth2 安全地存取 Gmail 帳戶，讀取信件並進行郵件操作。無需應用密碼，使用標準 OAuth2 流程。

## 核心功能

1. **OAuth2 認證**：首次使用時彈出瀏覽器進行授權
2. **信件檢索**：查詢最近 3 天內的信件（已讀和未讀均獲取）
3. **自動標記**：讀取後自動標記為已讀
4. **多語言支援**：支援 UTF-8, Big5, GBK 等多種編碼
5. **快取機制**：自動快取最多 50 封信件到本地 JSON
6. **默認限制**：每次查詢返回最新 20 封郵件

## 使用方法

透過執行 `scripts/gmail_controller.py` 來操作。

### 1. 初始化並檢索信件
```bash
# 默認獲取最新 20 個郵件（已讀和未讀）
python scripts/gmail_controller.py --action fetch

# 或指定數量
python scripts/gmail_controller.py --action fetch --limit 10
```

輸出：
```json
{
  "status": "success",
  "new_count": 5,
  "cached_count": 20,
  "newest": "2026-03-06T10:30:45",
  "oldest": "2026-03-01T09:15:00",
  "emails": [
    {
      "id": "msg_123",
      "from": "sender@example.com",
      "subject": "郵件主旨",
      "date": "Mon, 6 Mar 2026 10:30:45 +0000",
      "preview": "前 500 字內容..."
    }
  ]
}
```

### 2. 獲取快取統計
```bash
python scripts/gmail_controller.py --action stats
```

## 必要條件

1. **Google Cloud 專案** - 有效的 OAuth2 認證
2. **credentials.json** - 保存到 `workspace/credentials.json`
3. **首次認證** - 執行 `fetch` 時如無 token.json，會自動彈出瀏覽器授權

## 認證流程

**首次執行**：
```
1. 檢查 credentials.json
2. 若無 token.json，彈出瀏覽器
3. 用戶在 Google 登入頁授予「修改郵件」權限
4. Token 自動保存到 workspace/token.json
5. 後續執行自動使用 token（無需再授權）
```

**Token 自動刷新**：
- 當 token 過期時，系統自動使用 refresh_token 刷新
- 無需人工干預

## 設定檔

**必要**: `workspace/credentials.json` (來自 Google Cloud Console)

**可選**: `.env`
```ini
GMAIL_CHECK_INTERVAL_MINUTES=5    # Polling 間隔（若在 Dream Engine 中使用）
```

## 注意事項

- **權限**：使用 `gmail.modify` scope（讀取及標記信件）
- **查詢範圍**：固定查詢最近 3 天的信件（優化 API 配額）
- **快取限制**：最多保留 50 封，新信自動插入開頭
- **字符編碼**：自動偵測並支援多種編碼（UTF-8, Big5, GBK 等）

## 安全特性

- ✅ 使用 Google OAuth2（無密碼存儲）
- ✅ Token 自動加密保存
- ✅ 支援 Token 自動刷新
- ✅ 不支援刪除郵件（只能讀取和標記）
