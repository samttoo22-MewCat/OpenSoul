---
name: soul-status
description: 查看 OpenSoul 系統狀態、神經化學狀態和 Dream Engine 資訊
---

# 系統狀態

執行以下指令以查看系統狀態：

\`\`\`bash
cd /Users/mac/Desktop/coding/py/OpenSoul
python -m soul.interface.cli status
\`\`\`

## 顯示信息

- **Agent 資訊** — 名稱和版本
- **語言設定** — 當前語言偏好
- **神經化學狀態** — 多巴胺和血清素水平
- **學習率和驗證閾值** — 認知參數
- **搜尋廣度** — 記憶檢索範圍
- **Dream Engine 狀態** — 是否運行中
- **閒置時間** — 距離下次自動夢境的時間
- **上次夢境時間** — 最後一次記憶鞏固的時間

## 相關指令

- `soul-memory` — 記憶圖譜統計
- `soul-dream` — 手動觸發夢境
- `soul-chat` — 啟動對話模式
