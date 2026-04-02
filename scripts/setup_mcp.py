#!/usr/bin/env python3
"""
scripts/setup_mcp.py

OpenSoul MCP Plugin 環境設定腳本。
功能：
  1. 啟動 FalkorDB（與 setup_env.py 相同機制）
  2. 驗證 .env 中的 LLM / Embedding API Key
  3. 確認 fastmcp 已安裝（若無則自動安裝）
  4. 印出 Claude Desktop 的 mcpServers 設定片段
  5. 驗證 MCP server 可正常 import

用法：
    python scripts/setup_mcp.py              # 完整設定 + 啟動 HTTP server（前景，可看 log）
    python scripts/setup_mcp.py --stop       # 停止 MCP server + FalkorDB
    python scripts/setup_mcp.py --status     # 顯示目前狀態（含 Claude Desktop / Claude Code）
    python scripts/setup_mcp.py --cc-enable  # 在 Claude Code 全域啟用 opensoul MCP
    python scripts/setup_mcp.py --cc-disable # 從 Claude Code 全域停用 opensoul MCP
    python scripts/setup_mcp.py --no-serve   # 只完成設定，不啟動前景 server
    python scripts/setup_mcp.py --port 8765  # 自訂 HTTP server 埠號
    python scripts/setup_mcp.py --mcp-only   # 跳過 FalkorDB 啟動（由 setup_env 呼叫）

Ctrl+C：優雅停止 MCP server + FalkorDB
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# ── PATH 修正（macOS Docker Desktop）──────────────────────────────────────────
for _p in ["/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# ── 從 setup_env 引入 Docker 工具（避免重複維護）────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from setup_env import (  # type: ignore[import]
        find_docker_bin,
        detect_docker,
        detect_compose,
        check_port,
        wait_for_falkordb,
    )
    _IMPORTED_FROM_SETUP_ENV = True
except ImportError:
    _IMPORTED_FROM_SETUP_ENV = False

# ── rich 可選 ──────────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

PROJECT_ROOT   = Path(__file__).resolve().parent.parent
FALKORDB_HOST  = "localhost"
FALKORDB_PORT  = 6379
MCP_HTTP_PORT  = 7891
COMPOSE_FILE   = PROJECT_ROOT / "docker-compose.yml"
SERVER_MODULE  = "soul_mcp.server"
SERVER_SCRIPT  = PROJECT_ROOT / "soul_mcp" / "server.py"
PID_FILE       = PROJECT_ROOT / ".mcp_server.pid"


# ── 輸出工具 ───────────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"[INFO] {msg}") if not HAS_RICH else console.print(f"[bold cyan]ℹ[/bold cyan]  {msg}")

def ok(msg: str) -> None:
    print(f"[ OK ] {msg}") if not HAS_RICH else console.print(f"[bold green]✓[/bold green]  {msg}")

def warn(msg: str) -> None:
    print(f"[WARN] {msg}") if not HAS_RICH else console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")

def err(msg: str) -> None:
    print(f"[ERR ] {msg}") if not HAS_RICH else console.print(f"[bold red]✗[/bold red]  {msg}")

def header(title: str) -> None:
    if HAS_RICH:
        console.print(Panel(f"[bold white]{title}[/bold white]", style="blue"))
    else:
        print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── Docker / FalkorDB（工具函數從 setup_env.py import，此處僅定義 fallback）──
if not _IMPORTED_FROM_SETUP_ENV:
    import shutil
    import socket

    def find_docker_bin() -> str | None:  # type: ignore[no-redef]
        for c in [shutil.which("docker"), "/usr/local/bin/docker", "/opt/homebrew/bin/docker"]:
            if c and Path(c).exists():
                return c
        return None

    def detect_docker() -> bool:  # type: ignore[no-redef]
        docker_bin = find_docker_bin()
        if not docker_bin:
            return False
        try:
            r = subprocess.run([docker_bin, "info"], capture_output=True)
            if r.returncode == 0:
                return True
        except Exception:
            return False
        if platform.system() == "Darwin":
            desktop = Path("/Applications/Docker.app")
            if desktop.exists():
                warn("Docker daemon 未啟動，正在開啟 Docker Desktop…")
                subprocess.run(["open", "-a", "Docker"], check=False)
                start = time.time()
                while time.time() - start < 60:
                    time.sleep(2)
                    try:
                        if subprocess.run([docker_bin, "info"], capture_output=True).returncode == 0:
                            ok("Docker Desktop 已就緒")
                            return True
                    except Exception:
                        pass
                err("等待 Docker Desktop 逾時（60s）")
        return False

    def detect_compose() -> list[str] | None:  # type: ignore[no-redef]
        docker_bin = find_docker_bin()
        if docker_bin:
            try:
                if subprocess.run([docker_bin, "compose", "version"], capture_output=True).returncode == 0:
                    return [docker_bin, "compose"]
            except Exception:
                pass
        dc_bin = shutil.which("docker-compose")
        if dc_bin and subprocess.run([dc_bin, "version"], capture_output=True).returncode == 0:
            return [dc_bin]
        return None

    def check_port(host: str, port: int) -> bool:  # type: ignore[no-redef]
        try:
            s = socket.socket()
            s.settimeout(1)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    def wait_for_falkordb(timeout: int = 60) -> bool:  # type: ignore[no-redef]
        info(f"等待 FalkorDB 就緒（最多 {timeout}s）…")
        start = time.time()
        while time.time() - start < timeout:
            if check_port(FALKORDB_HOST, FALKORDB_PORT):
                return True
            time.sleep(1)
        return False


def start_falkordb() -> bool:
    """啟動 FalkorDB Docker 容器。"""
    if check_port(FALKORDB_HOST, FALKORDB_PORT):
        ok("FalkorDB 已在運行")
        return True

    if not detect_docker():
        err("Docker 未安裝或未啟動，請先安裝 Docker Desktop。")
        return False

    compose_cmd = detect_compose()
    if not compose_cmd:
        err("找不到 docker compose，請安裝 Docker Compose。")
        return False

    info("啟動 FalkorDB 容器…")
    result = subprocess.run(
        compose_cmd + ["-f", str(COMPOSE_FILE), "up", "-d", "falkordb"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        err(f"docker compose up 失敗：{result.stderr[:300]}")
        return False

    if wait_for_falkordb(timeout=60):
        ok("FalkorDB 啟動成功（localhost:6379）")
        return True
    else:
        err("FalkorDB 啟動逾時，請手動執行 docker-compose up -d")
        return False


def stop_mcp_server() -> None:
    """透過 PID 檔案停止正在運行的 MCP server 進程。"""
    if not PID_FILE.exists():
        info("MCP server 未在前景運行（無 .mcp_server.pid）")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        import signal as _signal
        os.kill(pid, _signal.SIGTERM)
        ok(f"MCP server（PID {pid}）已送出 SIGTERM")
        # 等待最多 5 秒確認退出
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)  # 0 = 只檢查存在性
            except ProcessLookupError:
                break
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        warn(f"無法停止 MCP server：{e}")
        PID_FILE.unlink(missing_ok=True)


def stop_falkordb() -> None:
    compose_cmd = detect_compose()
    if not compose_cmd:
        err("找不到 docker compose")
        return
    subprocess.run(compose_cmd + ["-f", str(COMPOSE_FILE), "down"], check=False)
    ok("FalkorDB 容器已停止")


def stop_all() -> None:
    """同時停止 MCP server 與 FalkorDB。"""
    stop_mcp_server()
    stop_falkordb()


# ── Claude Code MCP 開關 ───────────────────────────────────────────────────────

def is_claude_code_enabled() -> bool:
    """確認 opensoul 是否已在 Claude Code user config 中登記。"""
    result = subprocess.run(
        ["claude", "mcp", "get", "opensoul"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def enable_claude_code() -> bool:
    """將 opensoul MCP 加入 Claude Code user config（全域，所有專案皆可用）。"""
    if is_claude_code_enabled():
        ok("Claude Code 已啟用 opensoul（無需重複加入）")
        return True
    result = subprocess.run(
        [
            "claude", "mcp", "add", "--scope", "user", "opensoul",
            "-e", f"PYTHONPATH={PROJECT_ROOT}",
            "--", sys.executable, "-m", "soul_mcp.server",
        ],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Claude Code opensoul MCP 已啟用（全域）")
        info("重啟 Claude Code 後生效")
        return True
    else:
        err(f"啟用失敗：{result.stderr[:200]}")
        return False


def disable_claude_code() -> bool:
    """從 Claude Code user config 移除 opensoul MCP。"""
    if not is_claude_code_enabled():
        info("Claude Code 的 opensoul MCP 本來就未啟用")
        return True
    result = subprocess.run(
        ["claude", "mcp", "remove", "opensoul", "-s", "user"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("Claude Code opensoul MCP 已停用")
        return True
    else:
        err(f"停用失敗：{result.stderr[:200]}")
        return False


# ── .env 驗證 ──────────────────────────────────────────────────────────────────

def load_env() -> dict[str, str]:
    """讀取 .env 檔（不依賴 python-dotenv）。"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return {}
    result: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def check_env() -> bool:
    """確認必要的 API Key 已設定。"""
    env = load_env()

    provider = env.get("SOUL_LLM_PROVIDER", "anthropic").lower()
    emb_provider = env.get("SOUL_EMBEDDING_PROVIDER", "openai").lower()

    issues: list[str] = []

    # LLM Key
    if provider == "openrouter":
        if not env.get("OPENROUTER_API_KEY"):
            issues.append("OPENROUTER_API_KEY 未設定（SOUL_LLM_PROVIDER=openrouter）")
    else:
        if not env.get("ANTHROPIC_API_KEY"):
            issues.append("ANTHROPIC_API_KEY 未設定（SOUL_LLM_PROVIDER=anthropic）")

    # Embedding Key
    if emb_provider == "openai":
        if not env.get("OPENAI_API_KEY"):
            issues.append("OPENAI_API_KEY 未設定（SOUL_EMBEDDING_PROVIDER=openai）")

    if issues:
        for i in issues:
            err(f".env 缺少：{i}")
        err(f"請編輯 {PROJECT_ROOT / '.env'} 填入缺少的 Key")
        return False

    ok(f".env 驗證通過（LLM: {provider}，Embedding: {emb_provider}）")
    return True


# ── fastmcp 安裝確認 ───────────────────────────────────────────────────────────

def ensure_fastmcp() -> bool:
    """確認 fastmcp 已安裝，若無則嘗試 pip install。"""
    try:
        import fastmcp  # noqa: F401
        import importlib.metadata
        ver = importlib.metadata.version("fastmcp")
        ok(f"fastmcp 已安裝（v{ver}）")
        return True
    except ImportError:
        pass

    info("fastmcp 未安裝，正在安裝…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "fastmcp>=2.0"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("fastmcp 安裝成功")
        return True
    else:
        err(f"fastmcp 安裝失敗：{result.stderr[:200]}")
        return False


# ── MCP server import 驗證 ─────────────────────────────────────────────────────

def verify_server() -> bool:
    """確認 soul_mcp.server 可正常 import。"""
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0,'{PROJECT_ROOT}'); from soul_mcp.server import mcp; print('OK')"],
        capture_output=True, text=True,
    )
    if "OK" in result.stdout:
        ok("soul_mcp.server import 正常")
        return True
    else:
        err(f"soul_mcp.server import 失敗：{result.stderr[:300]}")
        return False


# ── Claude Desktop 設定輸出 ────────────────────────────────────────────────────

def print_claude_desktop_config() -> None:
    """印出 Claude Desktop 的 mcpServers 設定片段。"""
    config = {
        "mcpServers": {
            "opensoul": {
                "command": sys.executable,
                "args": ["-m", SERVER_MODULE],
                "cwd": str(PROJECT_ROOT),
                "env": {
                    "PYTHONPATH": str(PROJECT_ROOT)
                }
            }
        }
    }
    config_str = json.dumps(config, indent=2, ensure_ascii=False)

    # Claude Desktop config 路徑
    if platform.system() == "Darwin":
        claude_cfg_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        claude_cfg_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        claude_cfg_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    header("Claude Desktop 設定")
    if HAS_RICH:
        console.print(f"\n將以下內容加入 [bold]{claude_cfg_path}[/bold]：\n")
        console.print(Syntax(config_str, "json", theme="monokai"))
    else:
        print(f"\n將以下內容加入 {claude_cfg_path}：\n")
        print(config_str)

    # 嘗試自動寫入
    if claude_cfg_path.exists():
        try:
            existing = json.loads(claude_cfg_path.read_text(encoding="utf-8"))
            if "mcpServers" not in existing:
                existing["mcpServers"] = {}
            existing["mcpServers"]["opensoul"] = config["mcpServers"]["opensoul"]
            claude_cfg_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            ok(f"已自動寫入 {claude_cfg_path}")
            info("請重啟 Claude Desktop 使設定生效。")
        except Exception as e:
            warn(f"自動寫入失敗（{e}），請手動複製上方設定。")
    else:
        info(f"{claude_cfg_path} 不存在，請手動建立或先安裝 Claude Desktop。")


# ── 狀態顯示 ───────────────────────────────────────────────────────────────────

def show_status() -> None:
    header("OpenSoul MCP 狀態")

    falkordb_ok = check_port(FALKORDB_HOST, FALKORDB_PORT)

    env = load_env()
    provider = env.get("SOUL_LLM_PROVIDER", "anthropic").lower()
    llm_key = env.get("OPENROUTER_API_KEY") if provider == "openrouter" else env.get("ANTHROPIC_API_KEY")
    emb_key = env.get("OPENAI_API_KEY")
    soul_md = PROJECT_ROOT / "workspace" / "SOUL.md"
    cc_on = is_claude_code_enabled()

    try:
        import importlib.metadata
        fmcp_ver = importlib.metadata.version("fastmcp")
        fmcp_str = f"✓ v{fmcp_ver}"
    except Exception:
        fmcp_str = "✗ 未安裝"

    mcp_status = ""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            mcp_status = f"✓ 運行中 (PID {pid}, HTTP:{MCP_HTTP_PORT})"
        except Exception:
            mcp_status = "✗ PID 殘留（進程已死）"
    else:
        mcp_status = "─ 未在前景運行"

    try:
        if platform.system() == "Darwin":
            desktop_cfg = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        elif platform.system() == "Windows":
            desktop_cfg = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
        else:
            desktop_cfg = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
        desktop_on = "opensoul" in json.loads(desktop_cfg.read_text(encoding="utf-8")).get("mcpServers", {}) if desktop_cfg.exists() else False
    except Exception:
        desktop_on = False

    if HAS_RICH:
        from rich.table import Table as _RichTable
        t = _RichTable(show_header=False, box=None, padding=(0, 2))
        t.add_row("[dim]FalkorDB[/dim]",       f"[{'green' if falkordb_ok else 'red'}]{'✓ 運行中' if falkordb_ok else '✗ 未連線'}[/] ({FALKORDB_HOST}:{FALKORDB_PORT})")
        t.add_row("[dim]LLM API Key[/dim]",    f"[{'green' if llm_key else 'red'}]{'✓ 已設定' if llm_key else '✗ 未設定'}[/] ({provider})")
        t.add_row("[dim]Embed Key[/dim]",       f"[{'green' if emb_key else 'red'}]{'✓ 已設定' if emb_key else '✗ 未設定'}[/]")
        t.add_row("[dim]fastmcp[/dim]",         fmcp_str)
        t.add_row("[dim]SOUL.md[/dim]",         f"[{'green' if soul_md.exists() else 'yellow'}]{'✓ 存在' if soul_md.exists() else '⚠ 不存在（首次對話時自動建立）'}[/]")
        t.add_row("[dim]MCP server[/dim]",      mcp_status)
        t.add_row("[dim]Claude Desktop[/dim]",  f"[{'green' if desktop_on else 'red'}]{'✓ 已啟用' if desktop_on else '✗ 未設定'}[/]")
        t.add_row("[dim]Claude Code[/dim]",     f"[{'green' if cc_on else 'red'}]{'✓ 已啟用（全域）' if cc_on else '✗ 未啟用'}[/]")
        console.print(t)
    else:
        print(f"  FalkorDB    : {'✓ 運行中' if falkordb_ok else '✗ 未連線'} ({FALKORDB_HOST}:{FALKORDB_PORT})")
        print(f"  LLM API Key : {'✓ 已設定' if llm_key else '✗ 未設定'} ({provider})")
        print(f"  Embed Key   : {'✓ 已設定' if emb_key else '✗ 未設定'}")
        print(f"  fastmcp     : {fmcp_str}")
        print(f"  SOUL.md     : {'✓ 存在' if soul_md.exists() else '⚠ 不存在（首次對話時自動建立）'}")
        print(f"  MCP server  : {mcp_status}")
        print(f"  Claude Desktop: {'✓ 已啟用' if desktop_on else '✗ 未設定'}")
        print(f"  Claude Code : {'✓ 已啟用（全域）' if cc_on else '✗ 未啟用'}")


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="OpenSoul MCP Plugin 環境設定與啟動")
    parser.add_argument("--stop",        action="store_true", help="停止 MCP server + FalkorDB")
    parser.add_argument("--status",      action="store_true", help="顯示目前狀態")
    parser.add_argument("--cc-enable",   action="store_true", help="在 Claude Code 全域啟用 opensoul MCP")
    parser.add_argument("--cc-disable",  action="store_true", help="從 Claude Code 全域停用 opensoul MCP")
    parser.add_argument("--mcp-only",    action="store_true",
                        help="跳過 FalkorDB 啟動，僅執行 fastmcp 驗證與 Claude Desktop 設定（供 setup_env.py 呼叫）")
    parser.add_argument("--no-serve",    action="store_true",
                        help="完成設定後不啟動 HTTP server（僅設定，不進入前景模式）")
    parser.add_argument("--port", type=int, default=MCP_HTTP_PORT,
                        help=f"MCP HTTP server 埠號（預設 {MCP_HTTP_PORT}）")
    args = parser.parse_args()

    if args.stop:
        stop_all()
        return

    if args.status:
        show_status()
        return

    if args.cc_enable:
        enable_claude_code()
        return

    if args.cc_disable:
        disable_claude_code()
        return

    mcp_only: bool = args.mcp_only

    header("OpenSoul MCP Plugin 環境設定")

    # 顯示環境資訊
    system  = platform.system()
    machine = platform.machine()
    arch    = "arm64" if machine.lower() in ("arm64", "aarch64") else "amd64"
    py_ver  = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if HAS_RICH:
        from rich.table import Table as _RichTable
        _t = _RichTable(show_header=False, box=None, padding=(0, 2))
        _t.add_row("[dim]作業系統[/dim]",  f"[white]{system}[/white]")
        _t.add_row("[dim]CPU 架構[/dim]",  f"[white]{arch}[/white]")
        _t.add_row("[dim]Python[/dim]",    f"[white]{py_ver}[/white]")
        _t.add_row("[dim]專案路徑[/dim]",  f"[white]{PROJECT_ROOT}[/white]")
        console.print(_t)
    else:
        print(f"  OS:      {system}")
        print(f"  CPU:     {arch}")
        print(f"  Python:  {py_ver}")
        print(f"  Project: {PROJECT_ROOT}")

    failed: list[str] = []

    if not mcp_only:
        # Step 1: FalkorDB
        info("Step 1/4  啟動 FalkorDB…")
        if not start_falkordb():
            failed.append("FalkorDB")

        # Step 2: .env API Keys
        info("Step 2/4  驗證 API Keys…")
        if not check_env():
            failed.append(".env API Keys")

        step_prefix = "Step 3/4"
        step_prefix_4 = "Step 4/4"
    else:
        info("（--mcp-only 模式：跳過 FalkorDB 啟動與 API Key 驗證）")
        step_prefix = "Step 1/2"
        step_prefix_4 = "Step 2/2"

    # fastmcp
    info(f"{step_prefix}  確認 fastmcp…")
    if not ensure_fastmcp():
        failed.append("fastmcp")

    # server import
    info(f"{step_prefix_4}  驗證 MCP server…")
    if not verify_server():
        failed.append("soul_mcp.server")

    if failed:
        header("設定未完成")
        err(f"以下項目有問題：{', '.join(failed)}")
        sys.exit(1)

    # 成功 → 印出 / 寫入 Claude Desktop 設定
    print_claude_desktop_config()

    header("設定完成")
    ok("OpenSoul MCP Plugin 已就緒！")

    # --mcp-only 或 --no-serve：只設定，不啟動前景 server
    if mcp_only or args.no_serve:
        if not mcp_only:
            info("（--no-serve：不啟動前景 MCP server）")
            info("重啟 Claude Desktop 後，在工具列應可看到 opensoul 的三個工具。")
        return

    # ── 啟動 MCP server（HTTP 模式，前景，可看 log）──────────────────────────
    header(f"啟動 MCP server（HTTP：http://127.0.0.1:{args.port}）")
    info("按 Ctrl+C 停止 MCP server 與 FalkorDB")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONUNBUFFERED"] = "1"   # 確保 log 即時輸出

    mcp_process = subprocess.Popen(
        [sys.executable, "-m", "soul_mcp.server",
         "--transport", "http",
         "--host", "127.0.0.1",
         "--port", str(args.port)],
        cwd=PROJECT_ROOT,
        env=env,
        # 不設 capture_output → stdout/stderr 直接串流到終端
    )

    # 寫入 PID 檔案（供 --stop 使用）
    PID_FILE.write_text(str(mcp_process.pid), encoding="utf-8")
    ok(f"MCP server 已啟動（PID {mcp_process.pid}）")
    info(f"  stdio 模式（Claude Desktop）：python -m soul_mcp.server")
    info(f"  HTTP 模式（目前）：http://127.0.0.1:{args.port}")

    try:
        mcp_process.wait()
    except KeyboardInterrupt:
        info("\n接收到 Ctrl+C，正在關閉服務…")
    except Exception as e:
        err(f"MCP server 異常退出：{e}")
    finally:
        if mcp_process.poll() is None:
            mcp_process.terminate()
            try:
                mcp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mcp_process.kill()
        PID_FILE.unlink(missing_ok=True)
        ok("MCP server 已停止")

        # 從 Claude Code 移除 MCP 登記，讓 Claude 恢復原本狀態
        info("正在從 Claude Code 移除 opensoul MCP 登記…")
        disable_claude_code()
        info("下次使用請重新執行 setup_mcp.py（或 --cc-enable）")

        # 同時停止 FalkorDB
        info("正在停止 FalkorDB…")
        stop_falkordb()


if __name__ == "__main__":
    main()
