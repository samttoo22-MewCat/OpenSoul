"""
soul/interface/api.py

openSOUL FastAPI REST API。

端點：
  POST /chat              對話（主要入口）
  GET  /status            系統狀態快照
  POST /dream             觸發夢境週期
  POST /reflect           立即觸發反思
  GET  /proactive         取出 ARIA 主動訊息佇列
  GET  /memory/stats      圖譜統計
  POST /memory/search     記憶搜尋
  POST /memory/prune      手動修剪
  GET  /health            健康檢查
"""

from __future__ import annotations

import collections
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from soul.core.config import settings

logger = logging.getLogger("openSOUL.api")

# 靜態檔案目錄（與此檔案同層的 static/）
_STATIC_DIR = Path(__file__).parent / "static"


# ── 記憶體 Log Buffer ─────────────────────────────────────────────────────────

_LOG_BUFFER: collections.deque[dict[str, Any]] = collections.deque(maxlen=300)

_LEVEL_COLORS = {
    "DEBUG":    "dim",
    "INFO":     "info",
    "WARNING":  "warn",
    "ERROR":    "err",
    "CRITICAL": "err",
}


class _MemoryLogHandler(logging.Handler):
    """將 Python log record 推入 _LOG_BUFFER（FIFO，最多 300 筆）。"""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            _LOG_BUFFER.append({
                "ts":      record.created,
                "time":    self.formatTime(record, "%H:%M:%S"),
                "level":   record.levelname,
                "logger":  record.name,
                "message": record.getMessage(),
            })
        except Exception:  # pragma: no cover
            pass


_mem_handler = _MemoryLogHandler()
_mem_handler.setLevel(logging.DEBUG)


def _buf_append(level: str, logger_name: str, message: str) -> None:
    """直接向 _LOG_BUFFER 寫入一筆記錄（不依賴 logging handler 機制）。"""
    import datetime as _dt
    _LOG_BUFFER.append({
        "ts":      time.time(),
        "time":    _dt.datetime.now().strftime("%H:%M:%S"),
        "level":   level,
        "logger":  logger_name,
        "message": message,
    })


# 全域日誌函數供其他模組使用（特別是 soul.dream.reflection）
def log_buf(level: str, logger_name: str, message: str) -> None:
    """供其他模組使用的日誌函數。避免 logging handler 設定問題。"""
    _buf_append(level, logger_name, message)


class _SafeFormatter(logging.Formatter):
    """針對 Windows CP950 特化的日誌格式化器，自動將 Emoji 轉換為純文字。"""
    def format(self, record):
        msg = super().format(record)
        try:
            # 測試當前系統編碼是否支援
            msg.encode(sys.stdout.encoding or "utf-8")
            return msg
        except (UnicodeEncodeError, AttributeError):
            # 降級處理
            return (
                msg.replace("🛠️", "[Tool]")
                   .replace("📦", "[Args]")
                   .replace("🧠", "[Brain]")
                   .replace("📡", "[LLM]")
                   .replace("👨‍⚖️", "[Judge]")
                   .replace("📢", "[System]")
                   .replace("⚠️", "[WARN]")
                   .replace("✅", "[OK]")
                   .replace("❌", "[ERR]")
                   .replace("📤", "[OUT]")
            )

def _install_log_handler() -> None:
    """掛載記憶體 log handler 與詳細控制台 Handler。
    在 lifespan 內呼叫，確保在 uvicorn dictConfig 之後執行。
    """
    import sys
    
    # 1. 記憶體 Buffer Handler (用於 Web UI)
    root_logger = logging.getLogger()
    if _mem_handler not in root_logger.handlers:
        root_logger.addHandler(_mem_handler)
    
    # 2. 詳細控制台 Handler (用於終端機調試)
    # 檢查是否已存在類似的 StreamHandler，避免重複打印
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, _MemoryLogHandler) for h in root_logger.handlers)
    
    if not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        # 使用自定義的 SafeFormatter 代替原本的 Formatter
        formatter = _SafeFormatter(
            '\033[90m[%(asctime)s]\033[0m [\033[36m%(levelname)s\033[0m] [\033[33m%(name)s\033[0m] %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.setLevel(logging.DEBUG)

    # 確保主要組件的日誌都能傳遞並顯示
    log_names = ["openSOUL", "soul", "uvicorn", "uvicorn.error", "fastapi"]
    for name in log_names:
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = True
        # 如果該 logger 自身有其他 handler，且不是我們加的，可以考慮清理或調整
        # 這裡保持簡單，靠 propagate 到 root 處理即可

    _buf_append("INFO", "openSOUL.startup", "已強化控制台日誌輸出詳細度 (DEBUG level + Colors)")


# ── Lifespan（啟動/關閉事件）─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    應用程式啟動時初始化全域資源。

    降級模式（Degraded Mode）：
      若 FalkorDB 未啟動或 LLM 金鑰未設定，API 仍正常啟動。
      需要 DB 的端點（/chat, /dream…）會回傳 503 友善提示，
      UI（GET /）以及 /health 不受影響。
    """
    import logging
    logger = logging.getLogger("openSOUL.startup")

    # 安裝 log handler 並寫入啟動記錄
    _install_log_handler()
    _buf_append("INFO", "openSOUL.startup", "openSOUL 啟動 — 記憶體 log buffer 已就緒")

    app.state.agent        = None
    app.state.dream_engine = None
    app.state.startup_error: str | None = None

    try:
        from soul.core.agent import SoulAgent
        from soul.dream.engine import get_dream_engine
        from soul.dream.reflection import init_reflection_module
        from soul.memory.graph import get_graph_client, initialize_schemas

        client = get_graph_client()
        initialize_schemas(client)

        app.state.agent = SoulAgent(graph_client=client)
        app.state.dream_engine = get_dream_engine()
        app.state.dream_engine.start()

        # 反思模組（每 30 分鐘 ARIA 主動思考）
        agent = app.state.agent
        app.state.reflection = init_reflection_module(
            graph_client=client,
            llm_client=agent._llm,
            soul_loader=agent._loader,
            provider=agent._provider,
            agent=agent,
        )
        app.state.reflection.start()
        logger.info("openSOUL 啟動成功 ✓（含反思模組）")
        _buf_append("INFO", "openSOUL.startup", "openSOUL 啟動成功 ✓（含反思模組）")

    except Exception as exc:
        msg = f"啟動時發生錯誤（降級模式）：{exc}"
        logger.warning(msg)
        _buf_append("WARNING", "openSOUL.startup", msg)
        app.state.startup_error = msg

    yield

    if app.state.dream_engine is not None:
        app.state.dream_engine.stop()
    if getattr(app.state, "reflection", None) is not None:
        app.state.reflection.stop()


def _require_agent():
    """確認 Agent 可用，否則拋出 503（降級模式時使用）。"""
    if app.state.agent is None:
        detail = app.state.startup_error or "系統尚未就緒"
        raise HTTPException(
            status_code=503,
            detail=f"⚠️ 系統降級模式：{detail}\n\n"
                   "請確認：\n"
                   "1. FalkorDB 已啟動（docker compose up -d）\n"
                   "2. .env 中的 API Key 已填入\n"
                   "3. 重啟伺服器"
        )


app = FastAPI(
    title="openSOUL API",
    description="仿人類心智認知 AI 系統 REST API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HTTP 存取日誌 middleware（直接寫入 _LOG_BUFFER，繞過 logging 設定問題）────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse


class _AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        t0 = time.time()
        response: StarletteResponse = await call_next(request)
        elapsed = (time.time() - t0) * 1000
        path = request.url.path
        if request.url.query:
            path += "?" + request.url.query
        # 略過靜態資源與高頻輪詢
        if not path.startswith("/static") and path not in ("/proactive",):
            _buf_append("INFO", "http.access",
                        f"{request.method} {path} → {response.status_code} ({elapsed:.0f}ms)")
        return response


app.add_middleware(_AccessLogMiddleware)

# 掛載靜態檔案（CSS/JS/圖片等，若之後分離出來用）
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"!!! 422 Validation Error: {exc.errors()}\nBody: {exc.body}", flush=True)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )


# ── Request / Response Models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., description="使用者輸入訊息", min_length=1)
    session_id: str | None = Field(None, description="Session ID（留空自動建立）")


class ChatResponse(BaseModel):
    text: str
    session_id: str
    episode_id: str
    gating_passed: bool
    gating_action: str
    gating_score: float
    neurochem: dict[str, Any]
    memory_hits: dict[str, int]   # {episodes: N, concepts: N, procedures: N}
    # 🆕 工具決策可視化欄位
    recommended_tool: str = "none"
    judge_reasoning: str = ""
    judge_confidence: float = 0.0


class DreamRequest(BaseModel):
    replay_only: bool = Field(False, description="僅執行 LiDER 重播")


class DreamResponse(BaseModel):
    summary: str
    duration_seconds: float
    triggered_by: str
    error: str | None


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(10, ge=1, le=50)


# ── OpenAI Compatible API Models ──────────────────────────────────────────────

class OpenAIToolCallFunction(BaseModel):
    name: str
    arguments: str

class OpenAIToolCall(BaseModel):
    id: str
    type: str = "function"
    function: OpenAIToolCallFunction

class OpenAIChatRequestMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

class OpenAIFunction(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None

class OpenAITool(BaseModel):
    type: str = "function"
    function: OpenAIFunction

class OpenAIChatCompletionRequest(BaseModel):
    model: str
    messages: list[OpenAIChatRequestMessage]
    tools: list[OpenAITool] | None = None
    stream: bool = False
    temperature: float | None = None

class OpenAIChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None

class OpenAIChoice(BaseModel):
    index: int = 0
    message: OpenAIChoiceMessage
    finish_reason: str = "stop"

class OpenAIChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[OpenAIChoice]


# ── Session 管理（簡易記憶體 Store）─────────────────────────────────────────

_sessions: dict[str, Any] = {}


def _get_or_create_session(session_id: str | None) -> Any:
    from soul.core.session import Session
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    session = Session(session_id=session_id)
    _sessions[session.session_id] = session
    return session


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def ui_root() -> FileResponse:
    """提供瀏覽器互動介面（index.html）。"""
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "UI 尚未建立，請確認 soul/interface/static/index.html 存在"}, status_code=404)
    return FileResponse(str(index), media_type="text/html")


@app.get("/health")
async def health() -> dict[str, Any]:
    """健康檢查（即使降級模式也可通過）。"""
    ready = app.state.agent is not None
    return {
        "status": "ok" if ready else "degraded",
        "service": "openSOUL",
        "ready": ready,
        "provider": settings.soul_llm_provider,
        "model": settings.soul_llm_model,
        **({"error": app.state.startup_error} if not ready else {}),
    }


# ── 通用技能 Schema 建構 + 執行 ──────────────────────────────────────────────

# 技能 Schema 快取（避免每次重新掃描檔案系統）
_SKILL_SCHEMA_CACHE: dict[str, dict | None] = {}


def _build_skill_schema(skill_name: str) -> dict | None:
    """根據 skill 名稱動態建構 OpenAI function-calling schema。

    掃描 openclaw/skills/<skill_name>/scripts/ 目錄中的 Python 腳本，
    解析 argparse 定義自動產生 schema。如果沒有 scripts/ 或解析失敗，
    回傳基於 SKILL.md 描述的通用 schema。
    """
    if skill_name in _SKILL_SCHEMA_CACHE:
        return _SKILL_SCHEMA_CACHE[skill_name]

    import re as _re

    skills_dir = Path(settings.soul_project_root) / "openclaw" / "skills" / skill_name
    if not skills_dir.exists():
        _SKILL_SCHEMA_CACHE[skill_name] = None
        return None

    # 讀取描述
    description = f"OpenClaw skill: {skill_name}"
    skill_md = skills_dir / "SKILL.md"
    if skill_md.exists():
        try:
            content = skill_md.read_text(encoding="utf-8")
            lines = content.split("\n")
            if lines and lines[0].strip() == "---":
                for i in range(1, len(lines)):
                    if lines[i].strip() == "---":
                        for line in lines[1:i]:
                            if line.startswith("description:"):
                                desc_val = line.split(":", 1)[1].strip().strip("\"'")
                                if desc_val:
                                    description = desc_val
                        break
        except Exception:
            pass

    # 搜尋腳本，解析 argparse 來建構 parameters
    scripts_dir = skills_dir / "scripts"
    fn_name = skill_name.replace("-", "_")  # LLM 友好名稱

    if scripts_dir.exists():
        py_scripts = list(scripts_dir.glob("*.py"))
        if py_scripts:
            # 優先用第一個腳本（通常只有一個）
            script_path = py_scripts[0]
            try:
                src = script_path.read_text(encoding="utf-8")
                # 解析 add_argument 呼叫來建構 schema
                # 使用更嚴謹的解析：先抓取整個 add_argument(...) 塊
                properties = {}
                required = []
                
                # 匹配 add_argument(...) 整個區塊，不跨越下一個 add_argument
                arg_blocks = _re.findall(r'add_argument\((.*?)\)', src, _re.DOTALL)
                
                for block in arg_blocks:
                    # 在區塊內提取資訊
                    name_match = _re.search(r'["\']--(\w+)["\']', block)
                    if not name_match:
                        continue
                        
                    arg_name = name_match.group(1)
                    help_match = _re.search(r'help=["\']([^"\']*)["\']', block)
                    type_match = _re.search(r'type=(\w+)', block)
                    choices_match = _re.search(r'choices=\[([^\]]+)\]', block)
                    required_match = _re.search(r'required=(True)', block)
                    default_match = _re.search(r'default=([^,\)]+)', block)

                    help_text = help_match.group(1) if help_match else ""
                    type_name = type_match.group(1) if type_match else "str"
                    
                    prop: dict = {"description": help_text}
                    
                    if type_name == "int":
                        prop["type"] = "integer"
                    else:
                        prop["type"] = "string"
                        
                    if choices_match:
                        # 處理 choices=["a", "b"]
                        raw_choices = choices_match.group(1)
                        choices = [c.strip().strip("\"'") for c in raw_choices.split(",")]
                        prop["enum"] = choices
                        
                    if default_match:
                        # 處理 default="value" 或 default=20
                        val = default_match.group(1).strip().strip("\"'")
                        if val not in ("None", ""):
                            if type_name == "int" and val.isdigit():
                                prop["default"] = int(val)
                            else:
                                prop["default"] = val

                    properties[arg_name] = prop
                    if required_match:
                        required.append(arg_name)

                if properties:
                    schema = {
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "description": description,
                            "parameters": {
                                "type": "object",
                                "properties": properties,
                                "required": required,
                            },
                        },
                    }
                    _SKILL_SCHEMA_CACHE[skill_name] = schema
                    logger.info(f"[API] Schema 自動建構成功：{fn_name} ({len(properties)} 參數)")
                    return schema
            except Exception as e:
                logger.warning(f"[API] 解析腳本 {script_path} 失敗：{e}")

    # Fallback：用 SKILL.md 描述建構通用 schema（一個 query 參數）
    schema = {
        "type": "function",
        "function": {
            "name": fn_name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要傳遞給技能的指令或查詢內容",
                    }
                },
                "required": ["query"],
            },
        },
    }
    _SKILL_SCHEMA_CACHE[skill_name] = schema
    logger.info(f"[API] Schema fallback 建構：{fn_name} (通用 query 模式)")
    return schema


def _execute_skill(fn_name: str, tool_call: dict, buf_append) -> str:
    """通用技能執行器 — 根據 fn_name 找到對應腳本並執行。

    支援所有在 openclaw/skills/<name>/scripts/ 下有 Python 腳本的技能。
    """
    import json
    import subprocess
    import sys

    # fn_name 使用 _ 分隔，skill 目錄使用 - 分隔
    skill_dir_name = fn_name.replace("_", "-")
    skills_root = Path(settings.soul_project_root) / "openclaw" / "skills"
    skill_dir = skills_root / skill_dir_name
    scripts_dir = skill_dir / "scripts"

    if not scripts_dir.exists():
        buf_append("WARNING", "openSOUL.tool", f"技能 {skill_dir_name} 沒有 scripts/ 目錄")
        return f"技能 {skill_dir_name} 沒有可執行的腳本"

    # 找到腳本
    py_scripts = list(scripts_dir.glob("*.py"))
    if not py_scripts:
        buf_append("WARNING", "openSOUL.tool", f"技能 {skill_dir_name}/scripts/ 中沒有 Python 檔案")
        return f"技能 {skill_dir_name} 沒有可執行的 Python 腳本"

    script_path = py_scripts[0]

    # 解析 LLM 傳來的參數
    try:
        args_dict = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, KeyError):
        args_dict = {}

    # 建構 CLI 命令
    cmd = [sys.executable, str(script_path)]
    for key, value in args_dict.items():
        if value is not None and value != "":
            cmd.extend([f"--{key}", str(value)])

    buf_append("INFO", "openSOUL.tool", f"執行：{script_path.name} {args_dict}")
    logger.info(f"[API] 執行技能腳本：{' '.join(cmd)}")

    try:
        env = {
            **dict(__import__("os").environ), 
            "PYTHONIOENCODING": "utf-8",
            "SOUL_PROJECT_ROOT": str(settings.soul_project_root)
        }
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(settings.soul_project_root)),
        )
        if result.returncode == 0:
            buf_append("INFO", "openSOUL.tool", f"OK 技能 {fn_name} 執行成功")
            return result.stdout
        else:
            buf_append("ERROR", "openSOUL.tool",
                       f"技能 {fn_name} 失敗：{result.stderr[:300]}")
            return f"執行失敗：\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    except Exception as exc:
        buf_append("ERROR", "openSOUL.tool", f"技能 {fn_name} 異常：{str(exc)[:200]}")
        return f"執行異常: {exc}"


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    主要對話端點。

    - 整合 EcphoryRAG 記憶觸發
    - 基底核閘門驗證
    - 情節記憶寫入
    - 神經化學狀態更新
    """
    _require_agent()
    agent = app.state.agent
    dream_engine = app.state.dream_engine
    dream_engine.notify_interaction()

    session = _get_or_create_session(req.session_id)


    try:
        # 每次對話前重新載入 SOUL.md，確保能吃到使用者的手動修改
        agent.reload_soul()

        # ═══ 👨‍⚖️ 工具探索流程 ═══════════════════════════════════════════════════════
        # 🆕 直接探索所有可用工具並建構 Schema，交由 Agent 內部的 Judge 做唯一決策
        try:
            available_tools_info = agent._judge.discover_available_tools()
            tools = []
            for t_info in available_tools_info:
                name = t_info["name"]
                schema = _build_skill_schema(name)
                if schema:
                    tools.append(schema)
            logger.info(f"[API] 🔍 已探測並加載 {len(tools)} 個工具 Schema")
        except Exception as e:
            logger.error(f"[API] ❌ 工具探索失敗：{e}", exc_info=True)
            tools = []

        # 呼叫 Agent 進行對話與決策
        response = agent.chat(req.message, session, tools=tools)
        
        # 🆕 從 Agent 中提取最終決策資訊，用於 UI 顯示與後續流程
        decision = response.judge_decision
        recommended_tool = decision.get("recommended_tool", "none")
        reasoning = decision.get("reasoning", "")
        confidence = decision.get("confidence", 0.0)

        # 處理 Tool calls — 通用執行引擎
        if response.tool_calls:
            _buf_append("INFO", "openSOUL.tool",
                       f"ARIA 發出 {len(response.tool_calls)} 個工具呼叫")
            for tc in response.tool_calls:
                fn_name = tc.get("function", {}).get("name", "")
                _buf_append("INFO", "openSOUL.tool", f"執行工具：{fn_name}")

                # 安全檢查：只允許 Judge 推薦的工具
                norm_fn = fn_name.replace("-", "_")
                norm_rec = recommended_tool.replace("-", "_") if recommended_tool != "none" else "none"
                if norm_fn != norm_rec and norm_rec != "none":
                    _buf_append("WARNING", "openSOUL.tool",
                               f"工具 {fn_name} 不匹配 Judge 推薦的 {recommended_tool} — 略過")
                    continue

                content = _execute_skill(fn_name, tc, _buf_append)
                tool_result_msg = f"[技能 {fn_name} 執行結果]\n{content}"
                response = agent.chat(tool_result_msg, session, tools=[])
                break
    except Exception as exc:
        logger.exception("[/chat] 對話發生例外")
        _buf_append("ERROR", "openSOUL.api", f"[/chat] 例外：{exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    ctx = response.memory_context
    _buf_append("INFO", "openSOUL.chat",
                f"[chat] gate={response.gating_action} score={response.gating_score:.2f} "
                f"mem_ep={len(ctx.episodes)} mem_con={len(ctx.concepts)}")
    return ChatResponse(
        text=response.text,
        session_id=response.session_id,
        episode_id=response.episode_id,
        gating_passed=response.gating_passed,
        gating_action=response.gating_action,
        gating_score=response.gating_score,
        neurochem=response.neurochem,
        memory_hits={
            "episodes": len(ctx.episodes),
            "concepts": len(ctx.concepts),
            "procedures": len(ctx.procedures),
        },
        # 🆕 回傳決策細節給前端
        recommended_tool=recommended_tool,
        judge_reasoning=reasoning,
        judge_confidence=confidence,
    )


@app.post("/v1/chat/completions")
async def openai_chat_completions(req: OpenAIChatCompletionRequest) -> Any:
    """
    OpenAI API 相容端點。
    讓 OpenClaw (或其他 Agent 框架) 將 openSOUL 視為可控制的大腦。
    """
    _require_agent()
    agent = app.state.agent
    
    # [Debug] 列印 OpenClaw 傳進來的完整請求
    print(f"\n--- OpenClaw Request ---\n{req.model_dump_json(indent=2)}\n------------------------\n", flush=True)
    
    # 只取最後 10 筆避免 context 過長
    recent_messages = req.messages[-10:]
    
    # 找到最後一筆關鍵訊息 (user 或是 tool result)
    user_input = ""
    for msg in reversed(recent_messages):
        if msg.role == "user" and msg.content:
            raw_content = msg.content
            if isinstance(raw_content, list):
                # 處理 multi-modal content array (例如 {"type": "text", "text": "hello"})
                text_parts = [c.get("text", "") for c in raw_content if c.get("type") == "text"]
                user_input = "\n".join(text_parts)
            else:
                user_input = raw_content
            break
        elif msg.role == "tool" and msg.content:
            # 這是 OpenClaw 執行完工具後傳回來的結果，我們將它餵給 ARIA 當作她的感知輸入
            tool_name = msg.name or "未知工具"
            raw_content = msg.content
            if isinstance(raw_content, list):
                text_parts = [c.get("text", "") for c in raw_content if c.get("type") == "text"]
                content_text = "\n".join(text_parts)
            else:
                content_text = raw_content
            user_input = f"[技能 {tool_name} 執行結果]\n{content_text}"
            
            # 🆕 [Debug] 將工具結果也寫入 Session Log 與全域 Logger，讓網站前端能顯示出來
            from soul.core.config import logger
            
            # 判斷結果是否包含錯誤，調整日誌等級
            is_error = any(key in content_text.lower() for key in ["error", "exception", "failed", "traceback"])
            log_icon = "❌" if is_error else "🔧"
            
            log_msg = f"{log_icon} [工具回報] {tool_name} 執行結果：\n{content_text}"
            
            if is_error:
                logger.error(log_msg)
            else:
                logger.info(log_msg)
            
            session = _get_or_create_session("openclaw-main-brain")
            session.log("system" if not is_error else "error", log_msg)
            break
            
    if not user_input:
        user_input = "（繼續對話）"

    # 固定 Session 讓 OpenClaw 背景工作能延續上下文
    session = _get_or_create_session("openclaw-main-brain")

    try:
        agent.reload_soul()
        tools_dict = [t.model_dump(exclude_none=True) for t in req.tools] if req.tools else None
        response = agent.chat(user_input, session, tools=tools_dict)
    except Exception as exc:
        logger.exception("[/v1/chat/completions] 處理失敗")
        raise HTTPException(status_code=500, detail=str(exc))

    tc_list = None
    if response.tool_calls:
        tc_list = [OpenAIToolCall(**tc) for tc in response.tool_calls]

    resp_msg = OpenAIChoiceMessage(
        role="assistant",
        content=response.text,
        tool_calls=tc_list
    )

    import json as _json

    if req.stream:
        # OpenClaw 要求 SSE 串流，依標準 OpenAI chunk 格式輸出
        async def stream_generator():
            chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
            created_ts = int(time.time())

            # Chunk 1: role
            yield "data: " + _json.dumps({
                "id": chunk_id, "object": "chat.completion.chunk",
                "created": created_ts, "model": req.model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
            }) + "\n\n"

            # Chunk 2: content（一次全送，不切片）
            content_delta: dict[str, Any] = {"content": response.text or ""}
            if tc_list:
                content_delta["tool_calls"] = [
                    {"index": i, "id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for i, tc in enumerate(tc_list)
                ]
            yield "data: " + _json.dumps({
                "id": chunk_id, "object": "chat.completion.chunk",
                "created": created_ts, "model": req.model,
                "choices": [{"index": 0, "delta": content_delta, "finish_reason": None}]
            }) + "\n\n"

            # Chunk 3: finish
            yield "data: " + _json.dumps({
                "id": chunk_id, "object": "chat.completion.chunk",
                "created": created_ts, "model": req.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tc_list else "stop"}]
            }) + "\n\n"
            yield "data: [DONE]\n\n"

        print(f"--- API (SSE) 回傳給 OpenClaw ---\nContent: {response.text}\nTool Calls: {tc_list}\n---------------------------", flush=True)
        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    else:
        resp_obj = OpenAIChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=req.model,
            choices=[
                OpenAIChoice(
                    index=0,
                    message=resp_msg,
                    finish_reason="tool_calls" if tc_list else "stop"
                )
            ]
        )
        print(f"--- API 回傳給 OpenClaw ---\nContent: {response.text}\nTool Calls: {tc_list}\n---------------------------", flush=True)
        return resp_obj



@app.get("/debug/graph")
async def debug_graph(
    graph: str = "episodic",
    label: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """
    查詢圖譜節點屬性（Debug 用途）。
    graph: episodic | semantic | procedural
    label: 節點標籤過濾（空白表示全部）
    limit: 最多回傳幾筆
    """
    _require_agent()
    agent = app.state.agent
    client = agent._graph

    graph_map = {
        "episodic": client.episodic,
        "semantic": client.semantic,
        "procedural": client.procedural,
    }
    g = graph_map.get(graph, client.episodic)

    if label:
        cypher = f"MATCH (n:{label}) RETURN n LIMIT $lim"
    else:
        cypher = "MATCH (n) RETURN n LIMIT $lim"

    result = g.ro_query(cypher, params={"lim": limit}).result_set

    nodes = []
    for row in result:
        node = row[0]
        props = {}
        for k, v in node.properties.items():
            if k == "embedding":
                # 向量太長，只顯示維度
                props[k] = f"[Vector dim={len(v)}]"
            elif isinstance(v, str) and len(v) > 300:
                props[k] = v[:300] + "..."
            else:
                props[k] = v
        nodes.append({
            "labels": node.labels,
            "properties": props,
        })

    return {
        "graph": graph,
        "label_filter": label,
        "count": len(nodes),
        "nodes": nodes,
    }


@app.get("/status")
async def status() -> dict[str, Any]:
    """系統狀態快照：神經化學、圖譜統計、Dream Engine。"""
    _require_agent()
    from soul.memory.episodic import EpisodicMemory
    from soul.memory.procedural import ProceduralMemory
    from soul.memory.semantic import SemanticMemory

    agent = app.state.agent
    # 🆕 強制重新載入靈魂，確保 UI 能看到最新的 SOUL.md 變更 (如 edit_soul 後)
    agent.reload_soul()
    
    dream_engine = app.state.dream_engine
    client = agent._graph

    soul = agent.soul
    nc = soul.neurochem

    try:
        s_stats = SemanticMemory(client).stats()
        e_stats = EpisodicMemory(client).stats()
        p_stats = ProceduralMemory(client).stats()
    except Exception:
        s_stats = e_stats = p_stats = {}

    return {
        "agent": {"name": soul.name, "version": soul.version},
        "neurochem": nc.to_dict(),
        "memory": {
            "semantic": s_stats,
            "episodic": e_stats,
            "procedural": p_stats,
        },
        "dream_engine": dream_engine.status(),
    }


@app.post("/dream", response_model=DreamResponse)
async def dream(req: DreamRequest) -> DreamResponse:
    """手動觸發夢境鞏固週期（同步執行，可能需要數秒）。"""
    _require_agent()
    dream_engine = app.state.dream_engine

    if req.replay_only:
        from soul.dream.replay import LiDERReplay
        client = app.state.agent._graph
        report = LiDERReplay(client).run()
        return DreamResponse(
            summary=f"重播完成：{report.episodes_processed} 個情節",
            duration_seconds=0.0,
            triggered_by="api_replay_only",
            error=None,
        )

    report = dream_engine.dream_now(triggered_by="api")
    return DreamResponse(
        summary=report.summary(),
        duration_seconds=report.duration_seconds,
        triggered_by=report.triggered_by,
        error=report.error,
    )


@app.get("/memory/stats")
async def memory_stats() -> dict[str, Any]:
    """各記憶圖譜節點/邊統計。"""
    _require_agent()
    from soul.memory.episodic import EpisodicMemory
    from soul.memory.procedural import ProceduralMemory
    from soul.memory.semantic import SemanticMemory

    client = app.state.agent._graph
    return {
        "semantic": SemanticMemory(client).stats(),
        "episodic": EpisodicMemory(client).stats(),
        "procedural": ProceduralMemory(client).stats(),
    }


@app.post("/memory/search")
async def memory_search(req: MemorySearchRequest) -> dict[str, Any]:
    """向量 + 多跳圖譜搜尋。"""
    _require_agent()
    from soul.core.agent import EmbeddingService
    from soul.memory.retrieval import EcphoryRetrieval
    from soul.affect.neurochem import NeurochemState

    client = app.state.agent._graph
    nc = app.state.agent.soul.neurochem

    try:
        embedder = EmbeddingService()
        embedding = embedder.embed(req.query)
        ctx = EcphoryRetrieval(client).retrieve(
            query_embedding=embedding,
            serotonin=nc.serotonin,
            dopamine=nc.dopamine,
            top_k=req.top_k,
        )
    except Exception as exc:
        logger.exception("[/memory/search] 記憶搜尋發生例外")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "query": req.query,
        "episodes": ctx.episodes,
        "concepts": ctx.concepts,
        "procedures": ctx.procedures,
        "entities": ctx.entities,
    }


@app.post("/memory/prune")
async def memory_prune() -> dict[str, Any]:
    """手動觸發圖譜修剪。"""
    _require_agent()
    from soul.dream.pruning import GraphPruning
    client = app.state.agent._graph
    report = GraphPruning(client).run()
    return {
        "edges_pruned": report.edges_pruned,
        "nodes_archived": report.nodes_archived,
        "bridges_created": report.bridges_created,
        "details": report.details,
    }



@app.post("/reflect")
async def reflect_now() -> dict[str, Any]:
    """立即觸發一次 ARIA 的主動反思（不等待排程）。"""
    _require_agent()
    rm = getattr(app.state, "reflection", None)
    if rm is None:
        raise HTTPException(status_code=503, detail="反思模組未初始化")

    # 記錄反思開始
    _buf_append("INFO", "openSOUL.api", "[/reflect] 手動觸發內部反思...")

    import asyncio
    import logging
    loop = asyncio.get_event_loop()
    try:
        # 也嘗試通過 Python logger 記錄
        logger_reflect = logging.getLogger("soul.reflection")
        logger_reflect.info("[/reflect API] Starting reflection...")
        _buf_append("DEBUG", "openSOUL.api", f"[/reflect] soul.reflection logger level: {logger_reflect.level}, handlers: {len(logger_reflect.handlers)}")

        result = await loop.run_in_executor(None, rm.reflect_now)

        # 記錄反思結果
        logger_reflect.info(f"[/reflect API] Reflection complete: {result.action}")
        _buf_append("INFO", "openSOUL.api",
                    f"[/reflect] 反思完成: action={result.action}, reasoning={result.reasoning[:60]}")

        return {
            "action": result.action,
            "content": result.content,
            "reasoning": result.reasoning,
            "timestamp": result.timestamp,
        }
    except Exception as exc:
        _buf_append("ERROR", "openSOUL.api", f"[/reflect] 反思失敗: {exc}")
        raise HTTPException(status_code=500, detail=f"反思失敗: {exc}")


@app.get("/proactive")
async def get_proactive() -> dict[str, Any]:
    """
    取出 ARIA 主動訊息佇列（UI 輪詢用）。
    呼叫後佇列清空（一次性讀取）。
    """
    from soul.dream.reflection import pop_all_proactive
    items = pop_all_proactive()
    return {"messages": items, "count": len(items)}


@app.get("/gmail/emails")
async def gmail_emails(limit: int = 10) -> dict[str, Any]:
    """
    取得 Gmail 快取信件列表（供 ARIA 透過 web_fetch 呼叫）。
    ARIA 接收後用 LLM 摘要並回傳給使用者。
    """
    dream_engine = getattr(app.state, "dream_engine", None)
    if dream_engine is None or not hasattr(dream_engine, "_gmail"):
        raise HTTPException(status_code=503, detail="Gmail 模組尚未初始化")
    emails = dream_engine._gmail.get_cached_emails(limit=max(1, min(limit, 50)))
    stats = dream_engine._gmail.get_cache_stats()
    return {
        "emails": emails,
        "count": len(emails),
        "stats": stats,
    }


@app.post("/gmail/check")
async def gmail_check_now() -> dict[str, Any]:
    """手動觸發一次 Gmail 抓取（除錯 / 測試用）。"""
    dream_engine = getattr(app.state, "dream_engine", None)
    if dream_engine is None or not hasattr(dream_engine, "_gmail"):
        raise HTTPException(status_code=503, detail="Gmail 模組尚未初始化")
    if not dream_engine._gmail._enabled:
        raise HTTPException(status_code=400, detail="Gmail 尚未授權（workspace/credentials.json 不存在）")
    new_count = dream_engine._gmail.fetch_unseen()
    return {"new_emails_fetched": new_count, "total_cached": len(dream_engine._gmail._cache)}


@app.get("/logs")
async def get_logs(limit: int = 200, level: str = "") -> dict[str, Any]:
    """
    回傳伺服器端最新 log（由記憶體 buffer 提供）。
    level: DEBUG | INFO | WARNING | ERROR（空白表示全部）
    """
    entries = list(_LOG_BUFFER)
    if level:
        lvl = level.upper()
        entries = [e for e in entries if e["level"] == lvl]
    return {
        "total": len(entries),
        "entries": entries[-limit:],
    }


class ResetRequest(BaseModel):
    clear_context: bool = Field(True, description="清除歷史上下文 (Sessions)")
    clear_db: bool = Field(True, description="清除記憶資料庫 (Episodic/Semantic/Procedural)")
    clear_neuro: bool = Field(True, description="重置神經化學狀態 (Dopamine/Serotonin)")
    clear_soul_note: bool = Field(True, description="清除所有 Soul Note 筆記")

class SoulUpdateRequest(BaseModel):
    content: str = Field(..., description="SOUL.md 完整原始文字內容")


@app.get("/soul")
async def get_soul() -> dict[str, Any]:
    """讀取 SOUL.md 原始內容（供 UI 編輯器使用）。"""
    path = Path(settings.soul_workspace_path) / "SOUL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="SOUL.md 不存在")
    return {"content": path.read_text(encoding="utf-8")}


@app.put("/soul")
async def put_soul(req: SoulUpdateRequest) -> dict[str, Any]:
    """更新 SOUL.md 內容並立即重新載入代理人靈魂設定。"""
    _require_agent()
    path = Path(settings.soul_workspace_path) / "SOUL.md"
    path.write_text(req.content, encoding="utf-8")
    app.state.agent.reload_soul()
    logger.info("[/soul] SOUL.md 已更新並重新載入")
    _buf_append("INFO", "openSOUL.api", "SOUL.md 已儲存並重新載入")
    return {"status": "ok", "message": "SOUL.md 已儲存並重新載入"}


@app.get("/soul_notes")
async def get_soul_notes() -> dict[str, Any]:
    """取得歷史所有 Soul Note 與每日反思。"""
    try:
        from soul.core.soul_note import get_soul_note_manager
        manager = get_soul_note_manager()
        return {
            "status": "ok",
            "notes": manager.get_all_notes(),
            "reflections": manager.get_all_reflections()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"讀取筆記失敗: {e}")


@app.post("/reset")
async def reset_system(req: ResetRequest) -> dict[str, Any]:
    """選擇性重置系統組件。"""
    _require_agent()
    agent = app.state.agent

    details = []
    deleted_nodes = 0

    # 1. 清除三個記憶圖譜
    if req.clear_db:
        deleted_nodes = agent._graph.clear_all()
        details.append(f"資料庫({deleted_nodes}節點)")

    # 2. 重置神經化學至平衡狀態
    if req.clear_neuro:
        agent.soul.neurochem.reset_to_balanced()
        agent._loader.save_neurochem(agent.soul.neurochem)
        details.append("神經化學")

    # 3. 清空所有 Session
    if req.clear_context:
        _sessions.clear()
        details.append("歷史上下文")

    # 4. 清空 Soul Note
    if req.clear_soul_note:
        from soul.core.soul_note import get_soul_note_manager
        get_soul_note_manager().clear_all()
        details.append("Soul Note")

    msg = f"系統已重置以下項目：{', '.join(details)}" if details else "無項目被重置"

    logger.info(f"[/reset] {msg}")
    _buf_append("WARNING", "openSOUL.api", f"[/reset] {msg}")
    return {
        "status": "ok",
        "deleted_nodes": deleted_nodes,
        "message": msg,
        "details": details
    }


# ── Entry Point ───────────────────────────────────────────────────────────────

def serve() -> None:
    """啟動 FastAPI 伺服器（供 CLI 或直接執行使用）。"""
    import uvicorn
    uvicorn.run(
        "soul.interface.api:app",
        host=settings.soul_api_host,
        port=settings.soul_api_port,
        reload=settings.soul_api_reload,
    )


if __name__ == "__main__":
    serve()
