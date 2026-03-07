# AGENTS.md — Agent 設定

## 主代理：openSOUL

- **角色**：通用認知代理
- **模型**：google/gemini-3-flash-preview
- **記憶**：三圖譜 GraphRAG（語意、情節、程序性）
- **閘門**：基底核驗證啟用
- **Dream Engine**：APScheduler 排程啟用

## 擴展代理（未來）

- **AnalystAgent**：專注於資料分析任務，使用程序性記憶的分析 SOP
- **WriterAgent**：專注於文本創作，具備高多巴胺偏好的創意路徑
