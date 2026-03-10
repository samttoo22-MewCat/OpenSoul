---
name: browser-control
description: 使用 SeleniumBase UC (Undetected Chromedriver) 模式控制瀏覽器。可用於繞過自動化偵測、讀取動態網頁內容、截圖以及進行網頁互動（點擊、輸入）。當需要處理複雜網頁或機器人驗證時使用此工具。
---

# Browser Control (SeleniumBase UC Mode)

此技能允許 ARIA 使用具備反偵測能力的瀏覽器來存取網頁。這在處理需要 JavaScript 渲染、Cloudflare 防護或複雜互動的網站時非常有用。

## 核心功能

1. **繞過偵測**：使用 `uc=True` 模式，模擬真實使用者行為。
2. **網頁截圖**：獲取頁面視覺狀態。
3. **動態內容**：讀取完整渲染後的 HTML。
4. **互動操作**：支援點擊、輸入、捲動等。

## 使用方法

透過執行 `scripts/browser_controller.py` 來操作。

### 1. 獲取網頁內容 (Rendered HTML/Markdown)
```bash
python scripts/browser_controller.py --action fetch --url "https://example.com"
```

### 2. 獲取網頁截圖
```bash
python scripts/browser_controller.py --action screenshot --url "https://example.com"
```

### 3. 執行複雜互動 (範例：登入或搜尋)
```bash
python scripts/browser_controller.py --action interact --url "https://google.com" --steps '[{"type": "type", "selector": "input[name=q]", "text": "openSOUL AI"}, {"type": "click", "selector": "input[name=btnK]"}]'
```

## 注意事項
- **視窗顯示**：在 Windows 環境下會彈出實體 Chrome 視窗。
- **中文支援**：原生支援中文輸入與顯示。
- **性能**：啟動瀏覽器較慢（約 5-10 秒），僅在必要時使用。
