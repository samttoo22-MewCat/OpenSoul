---
name: agent-browser
description: 使用 agent-browser CLI 控制無頭瀏覽器進行網頁自動化，支援導航、點擊、截圖、存取性快照、表單填寫、PDF 輸出及 JavaScript 執行。適合需要與動態網頁互動或擷取視覺資訊時使用。
homepage: https://github.com/vercel-labs/agent-browser
metadata:
  {
    "openclaw":
      {
        "emoji": "🌐",
        "requires": { "bins": ["agent-browser"] },
        "install":
          [
            {
              "id": "npm",
              "kind": "npm",
              "package": "agent-browser",
              "global": true,
              "bins": ["agent-browser"],
              "label": "Install agent-browser via npm (global)",
            },
            {
              "id": "brew",
              "kind": "brew",
              "formula": "agent-browser",
              "bins": ["agent-browser"],
              "label": "Install agent-browser via Homebrew",
            },
          ],
      },
  }
---

# agent-browser

Rust-based headless browser CLI optimized for AI agents. Uses Chrome DevTools Protocol (CDP) with Chrome for Testing.

## 安裝後設定

安裝完成後需下載 Chrome 執行環境：

```bash
agent-browser install
# Linux 需要系統套件：
agent-browser install --with-deps
```

## 使用時機（觸發情境）

- 需要截取網頁畫面
- 需要與 JavaScript 渲染的頁面互動
- 需要填寫表單、點擊按鈕
- 需要分析頁面存取性結構（accessibility tree）
- 需要生成網頁 PDF
- 需要在頁面中執行 JavaScript

## 核心指令

### 導航與截圖

```bash
# 前往網址
agent-browser navigate --url "https://example.com"

# 截圖（返回 base64 PNG）
agent-browser screenshot --url "https://example.com"

# 生成 PDF
agent-browser pdf --url "https://example.com" --output page.pdf
```

### 存取性快照（結構分析）

```bash
# 取得頁面 ARIA tree（含 element refs 供後續操作）
agent-browser snapshot --url "https://example.com"
```

### 元素互動

```bash
# 用自然語言或 ARIA 名稱找元素（返回 ref）
agent-browser find --url "https://example.com" --query "search bar"

# 點擊（使用 snapshot 或 find 取得的 ref）
agent-browser click --url "https://example.com" --ref "ref_42"

# 輸入文字
agent-browser type --url "https://example.com" --ref "ref_42" --text "hello world"

# 填寫表單（select/checkbox/input）
agent-browser fill --url "https://example.com" --ref "ref_10" --value "option_text"
```

### JavaScript 執行

```bash
agent-browser eval --url "https://example.com" --expression "document.title"
```

### 進階功能

```bash
# 網路攔截（模擬 API 回應）
agent-browser mock --url "https://example.com" --pattern "/api/data" --response '{"mocked":true}'

# 裝置模擬
agent-browser navigate --url "https://example.com" --device "iPhone 14"

# 多標籤管理
agent-browser tabs --list
```

## 工作流程建議

1. 先用 `snapshot` 取得頁面結構與 element refs
2. 用 `find` 定位目標元素（若 snapshot 結果難以分析）
3. 用 `click` / `type` / `fill` 執行互動
4. 用 `screenshot` 確認結果

## 注意事項

- 首次使用前須執行 `agent-browser install` 下載 Chrome
- 截圖回傳 base64 PNG，可直接嵌入 markdown
- `snapshot` 回傳完整 ARIA tree，比截圖更適合結構分析
