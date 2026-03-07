#!/usr/bin/env python3
"""
scripts/setup_env.py

openSOUL 環境自動設定腳本。
自動偵測作業系統與 CPU 架構，啟動 FalkorDB Docker 容器。

用法：
    python scripts/setup_env.py           # 啟動容器
    python scripts/setup_env.py --stop    # 停止容器
    python scripts/setup_env.py --status  # 顯示狀態
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import signal
from pathlib import Path

# ── 確保 /usr/local/bin 在 subprocess 的 PATH 中（macOS Docker Desktop）──────
_extra_paths = ["/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"]
_env_path = os.environ.get("PATH", "")
for _p in _extra_paths:
    if _p not in _env_path:
        os.environ["PATH"] = _p + os.pathsep + _env_path
        _env_path = os.environ["PATH"]

# ── 嘗試使用 rich（已在 pyproject.toml 中），退回 print ────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import print as rprint
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None  # type: ignore[assignment]
    HAS_RICH = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
FALKORDB_HOST = "localhost"
FALKORDB_PORT = 6379
HEALTH_TIMEOUT = 900   # 最多等待幾秒

# ── 安裝指引 URL ───────────────────────────────────────────────────────────
INSTALL_URLS = {
    ("Darwin", "arm64"): "https://docs.docker.com/desktop/install/mac-install/",
    ("Darwin", "amd64"): "https://docs.docker.com/desktop/install/mac-install/",
    ("Linux",  "arm64"): "https://docs.docker.com/engine/install/",
    ("Linux",  "amd64"): "https://docs.docker.com/engine/install/",
    ("Windows","amd64"): "https://docs.docker.com/desktop/install/windows-install/",
}


# ── 工具函數 ───────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold cyan]ℹ[/bold cyan]  {msg}")
    else:
        print(f"[INFO] {msg}")


def ok(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold green]✓[/bold green]  {msg}")
    else:
        print(f"[ OK ] {msg}")


def warn(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")
    else:
        print(f"[WARN] {msg}")


def err(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold red]✗[/bold red]  {msg}")
    else:
        print(f"[ERR ] {msg}")


def header(title: str) -> None:
    if HAS_RICH:
        console.print(Panel(f"[bold white]{title}[/bold white]", style="blue"))
    else:
        print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── 環境偵測 ───────────────────────────────────────────────────────────────

def detect_environment() -> tuple[str, str]:
    """
    偵測作業系統與 CPU 架構。
    回傳: (system, arch)
      system: "Darwin" | "Linux" | "Windows"
      arch:   "arm64"  | "amd64"
    """
    system  = platform.system()   # Darwin / Linux / Windows
    machine = platform.machine()  # arm64 / x86_64 / AMD64 / aarch64

    # 規格化 arch
    arch = "arm64" if machine.lower() in ("arm64", "aarch64") else "amd64"
    return system, arch


def find_docker_bin() -> str | None:
    """找到 docker 可執行檔路徑（含 macOS Docker Desktop 慣用路徑）。"""
    candidates = [
        shutil.which("docker"),
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def detect_docker() -> bool:
    """確認 Docker daemon 是否在運行中。若 macOS 上 daemon 未啟，嘗試開啟 Docker Desktop。"""
    docker_bin = find_docker_bin()
    if not docker_bin:
        return False

    # 先測試 daemon 是否已在運行
    try:
        r = subprocess.run([docker_bin, "info"], capture_output=True)
        if r.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    # macOS：daemon 未啟動 → 嘗試自動開啟 Docker Desktop
    if platform.system() == "Darwin":
        desktop = Path("/Applications/Docker.app")
        if desktop.exists():
            warn("Docker daemon 未啟動，正在開啟 Docker Desktop…")
            subprocess.run(["open", "-a", "Docker"], check=False)
            # 等待 daemon 就緒（最多 60 秒）
            start = time.time()
            while time.time() - start < 60:
                time.sleep(2)
                try:
                    r2 = subprocess.run([docker_bin, "info"], capture_output=True)
                    if r2.returncode == 0:
                        ok("Docker Desktop 已就緒")
                        return True
                except Exception:
                    pass
            err("等待 Docker Desktop 逾時（60s）")
            return False

    return False


def detect_compose() -> list[str] | None:
    """
    找到可用的 Docker Compose 命令。
    優先使用 v2（docker compose），退回 v1（docker-compose）。
    """
    docker_bin = find_docker_bin()

    # v2：Docker Compose Plugin
    if docker_bin:
        try:
            r = subprocess.run(
                [docker_bin, "compose", "version"],
                capture_output=True,
            )
            if r.returncode == 0:
                return [docker_bin, "compose"]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # v1：獨立安裝的 docker-compose
    dc_bin = shutil.which("docker-compose")
    if dc_bin:
        try:
            r = subprocess.run([dc_bin, "version"], capture_output=True)
            if r.returncode == 0:
                return [dc_bin]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return None


def wait_for_falkordb(timeout: int = HEALTH_TIMEOUT) -> bool:
    """
    輪詢 localhost:6379，等待 FalkorDB 就緒。
    回傳 True 表示成功連通，False 表示逾時。
    """
    info(f"等待 FalkorDB 就緒（最多 {timeout}s）…")
    start = time.time()
    attempts = 0
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((FALKORDB_HOST, FALKORDB_PORT))
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            attempts += 1
            if attempts % 5 == 0:
                elapsed = int(time.time() - start)
                info(f"  … {elapsed}s 已過，繼續等待")
            time.sleep(1)
    return False


def check_port(host: str, port: int) -> bool:
    """測試 TCP 連通性（不等待）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def cleanup_api_port(port: int = 8002, timeout: int = 5) -> None:
    """
    檢查 API 端口是否被佔用。

    ⚠️  DANGER: 自動終止進程邏輯已禁用（Windows netstat 解析易誤殺系統進程）

    改為：
    1. 檢查端口狀態
    2. 若有佔用，提示用戶手動清理（確保安全）
    """
    if not check_port("localhost", port):
        # 端口未被佔用，無需清理
        return

    warn(f"端口 {port} 被佔用。請手動終止佔用的進程，或重啟 Docker Desktop。")

    # 不自動終止進程 - 太危險了！
    # Windows netstat 輸出解析易出錯，可能誤殺系統進程或 Docker Desktop
    # 改為提示用戶手動清理


def init_openclaw_config(config_dir: Path) -> None:
    """
    初始化 openclaw.json（如不存在）。
    配置為：禁用 OpenClaw 本地 Markdown 記憶層，使用 openSOUL 的 FalkorDB 系統。
    參考：https://docs.openclaw.ai/gateway/configuration
    """
    config_file = config_dir / "openclaw.json"

    import json

    # 如果已存在，跳過初始化但執行修復
    if config_file.exists():
        fix_openclaw_config(config_dir)
        return

    try:
        # 根據 OpenClaw 官方文檔建立配置
        # 禁用 OpenClaw 本地 Markdown 記憶（memory/YYYY-MM-DD.md），依賴 openSOUL FalkorDB
        config = {
            "gateway": {
                "bind": "lan",      # 跨平台綁定模式
                "port": 3410
            },
            # 禁用 OpenClaw 的 Markdown 記憶檔案系統
            "memorySearch": {
                "enabled": False    # 禁用本地記憶搜尋（改用 openSOUL FalkorDB）
            },
            # 禁用上下文修剪（OpenClaw 內部緩存）
            "contextPruning": {
                "enabled": False    # 禁用 OpenClaw 的上下文修剪機制
            },
            # 禁用記憶壓縮與刷新（memoryFlush）
            "compaction": {
                "memoryFlush": {
                    "enabled": False # 禁用 Markdown diary 自動儲存
                }
            }
        }

        config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        ok(f"✓ 已建立 openclaw.json 於 {config_file}")
        info("   配置詳情：")
        info("   • memorySearch.enabled = false    （禁用本地記憶檔案）")
        info("   • contextPruning.enabled = false  （禁用 OpenClaw 緩存）")
        info("   • compaction.memoryFlush.enabled = false （禁用 Markdown diary）")
        info("   ✓ 所有記憶全數依賴 openSOUL 的 FalkorDB 系統")
    except Exception as e:
        err(f"建立 openclaw.json 失敗：{e}")


def fix_openclaw_config(config_dir: Path) -> None:
    """
    自動修正 OpenClaw 設定檔中的常見問題與記憶層配置。
    確保禁用 OpenClaw 本地記憶，全數使用 openSOUL FalkorDB。
    """
    config_file = config_dir / "openclaw.json"
    if not config_file.exists():
        return

    import json
    try:
        content = config_file.read_text(encoding="utf-8")
        data = json.loads(content)
        changed = False

        # 1. 修正 bind 模式（0.0.0.0 在新版已不支援）
        gateway = data.get("gateway", {})
        if gateway.get("bind") == "0.0.0.0":
            info("偵測到舊版 bind 設定 (0.0.0.0)，自動優化為 'lan' 模式以確保跨平台相容性。")
            gateway["bind"] = "lan"
            changed = True

        # 2. 確保禁用 OpenClaw 記憶搜尋（使用 openSOUL 的 FalkorDB）
        memory_search = data.get("memorySearch", {})
        if memory_search.get("enabled", True) != False:
            info("禁用 OpenClaw memorySearch → 全部使用 openSOUL FalkorDB")
            data["memorySearch"] = {"enabled": False}
            changed = True

        # 3. 禁用 OpenClaw 上下文修剪（避免內部緩存）
        context_pruning = data.get("contextPruning", {})
        if context_pruning.get("enabled", True) != False:
            info("禁用 OpenClaw contextPruning（內部快取機制）")
            data["contextPruning"] = {"enabled": False}
            changed = True

        # 4. 禁用記憶壓縮與 Markdown diary（避免本地記憶文件）
        compaction = data.get("compaction", {})
        memory_flush = compaction.get("memoryFlush", {})
        if memory_flush.get("enabled", True) != False:
            info("禁用 OpenClaw memoryFlush（Markdown diary 記憶）")
            compaction["memoryFlush"] = {"enabled": False}
            data["compaction"] = compaction
            changed = True

        # 5. 移除不支援的 version 欄位
        if "version" in data:
            info("移除 openclaw.json 中不支援的 'version' 欄位。")
            del data["version"]
            changed = True

        if changed:
            config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            ok("OpenClaw 配置檔已自動更新（禁用本地記憶層）。")
    except Exception as e:
        warn(f"嘗試自動修正 openclaw.json 時發生錯誤（跳過）：{e}")


def get_openclaw_env() -> dict[str, str]:
    """產出一致的 OpenClaw Docker 環境變數。"""
    env = os.environ.copy()
    openclaw_dir = PROJECT_ROOT / "openclaw"
    
    config_dir = Path.home() / ".openclaw"
    workspace_dir = PROJECT_ROOT / "workspace"
    project_skills_dir = openclaw_dir / "skills"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    
    # 執行自動修復邏輯
    fix_openclaw_config(config_dir)
    
def sync_directory(src: Path, dst: Path) -> bool:
    """
    通用路徑同步函數。
    Windows: 使用 robocopy (更快、支援鏡像)。
    Unix/Mac: 使用 rsync -av --delete。
    """
    if not src.exists():
        return False
    
    dst.mkdir(parents=True, exist_ok=True)
    
    try:
        if sys.platform == "win32":
            # /MIR: 鏡像目錄
            # /R:0 /W:0: 失敗不重試，立即跳過
            # Robocopy 返回值 0-7 均代表成功 (0: 無變動, 1: 複製成功, etc.)
            subprocess.run(
                ["robocopy", str(src), str(dst), "/MIR", "/R:0", "/W:0", "/NFL", "/NDL", "/NJH", "/NJS"],
                check=False, capture_output=True
            )
            return True
        else:
            # Unix / macOS: 使用 rsync
            if shutil.which("rsync"):
                subprocess.run(
                    ["rsync", "-av", "--delete", f"{src}/", str(dst)],
                    check=True, capture_output=True
                )
                return True
            else:
                # 備援：原生 Python 取代
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                return True
    except Exception as e:
        warn(f"同步 {src.name} 失敗：{e}")
        return False


def get_openclaw_env() -> dict[str, str]:
    """產出一致的 OpenClaw Docker 環境變數。"""
    env = os.environ.copy()
    openclaw_dir = PROJECT_ROOT / "openclaw"

    config_dir = Path.home() / ".openclaw"
    workspace_dir = PROJECT_ROOT / "workspace"
    project_skills_dir = openclaw_dir / "skills"

    config_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # 🆕 初始化或修複 openclaw.json（禁用本地記憶層，使用 openSOUL）
    init_openclaw_config(config_dir)
    
    # ── OPENCLAW_GATEWAY_TOKEN 自動生成邏輯 ─────────────────────────────────
    token = env.get("OPENCLAW_GATEWAY_TOKEN")
    if not token:
        # 嘗試從 .env 讀取
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        
        if not token:
            # 隨機生成 32 節點 hex
            import secrets
            token = secrets.token_hex(32)
            info(f"為 OpenClaw 生成了新的 Gateway Token。")
    
    env["OPENCLAW_GATEWAY_TOKEN"] = token

    # 🆕 精簡同步邏輯 (Selective Sync)
    # 僅同步必要技能，減少磁碟 I/O。基礎技能已在 Docker 內建。
    ESSENTIAL_SKILLS = ["soul-note", "edit-soul", "browser-control", "healthcheck", "session-logs", "gmail"]
    
    if project_skills_dir.exists():
        target_skills_dir = config_dir / "skills"
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        
        info(f"正在同步核心技能至: {target_skills_dir}")
        sync_count = 0
        for skill in ESSENTIAL_SKILLS:
            src_skill = project_skills_dir / skill
            if src_skill.exists():
                if sync_directory(src_skill, target_skills_dir / skill):
                    sync_count += 1
        
        if sync_count > 0:
            ok(f"成功同步 {sync_count} 個專案核心技能。")
        
        # 告知 Docker 使用該路徑下的 skills
        env["OPENCLAW_SKILLS_PATH"] = target_skills_dir.absolute().as_posix()

    # 強制注入絕對路徑
    env["OPENCLAW_CONFIG_DIR"] = config_dir.absolute().as_posix()
    env["OPENCLAW_WORKSPACE_DIR"] = workspace_dir.absolute().as_posix()
    env["OPENCLAW_GATEWAY_BIND"] = "lan"
    env["SOUL_PROJECT_ROOT"] = PROJECT_ROOT.absolute().as_posix()
    
    return env


# ── 主要動作 ───────────────────────────────────────────────────────────────

def action_start(compose_cmd: list[str]) -> None:
    """啟動 FalkorDB 容器與 OpenClaw 容器。"""
    system, arch = detect_environment()
    info("啟動 FalkorDB 容器…")
    env = get_openclaw_env() # 共用環境資訊

    # 🆕 強化環境變數同步：將關鍵變數寫入 .env 文件，使 docker-compose 能讀取
    # 確保 Judge 在 Docker 容器中與原生 API 能共享配置
    env_file = PROJECT_ROOT / ".env"
    try:
        # 讀取現有 .env
        env_content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        lines = env_content.splitlines()
        
        # 需要持久化的鍵值配對
        persistence_keys = [
            "OPENCLAW_SKILLS_PATH", 
            "OPENCLAW_CONFIG_DIR", 
            "OPENCLAW_WORKSPACE_DIR", 
            "OPENCLAW_GATEWAY_TOKEN",
            "SOUL_PROJECT_ROOT"
        ]
        
        updated = False
        for key in persistence_keys:
            if key in env:
                # 移除舊行並加入新行
                val = env[key]
                new_line = f"{key}={val}"
                
                # 檢查是否已存在且相同
                exists = False
                for i, line in enumerate(lines):
                    if line.startswith(f"{key}="):
                        if line != new_line:
                            lines[i] = new_line
                            updated = True
                        exists = True
                        break
                
                if not exists:
                    lines.append(new_line)
                    updated = True
        
        if updated:
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok("已更新 .env 檔案以確保環境變數一致性。")
    except Exception as e:
        warn(f"無法同步 .env：{e}")

    # 確保 Docker daemon 已完全啟動（Windows 可能需要更多時間）
    start_time = time.time()
    while time.time() - start_time < 30:
        if detect_docker():
            break
        time.sleep(1)

    try:
        subprocess.run(
            compose_cmd + ["-f", str(COMPOSE_FILE), "up", "-d", "--remove-orphans"],
            env=env,
            check=True,
            cwd=PROJECT_ROOT,
        )
    except subprocess.CalledProcessError as exc:
        err(f"docker compose up 失敗：{exc}")
        sys.exit(1)

    if wait_for_falkordb():
        ok("FalkorDB 已就緒！")
    else:
        err(f"等待逾時（>{HEALTH_TIMEOUT}s），FalkorDB 可能啟動失敗。")
        err("請執行 `docker logs opensoul-falkordb` 查看詳細錯誤。")
        sys.exit(1)

    # 啟動 OpenClaw
    openclaw_dir = PROJECT_ROOT / "openclaw"
    if openclaw_dir.exists() and (openclaw_dir / "docker-compose.yml").exists():
        info("檢查 OpenClaw 鏡像...")
        image_exists = False
        try:
            r = subprocess.run(["docker", "images", "-q", "openclaw:local"], capture_output=True, text=True)
            if r.stdout.strip():
                image_exists = True
        except Exception:
            pass

        if not image_exists:
            warn("未偵測到 openclaw:local 鏡像，正在啟動構建 (此過程在 Raspberry Pi 上可能較慢)...")
            docker_setup_script = openclaw_dir / "docker-setup.sh"
            dockerfile_path = openclaw_dir / "Dockerfile"
            
            build_success = False
            if dockerfile_path.exists():
                try:
                    if docker_setup_script.exists():
                        subprocess.run(["bash", "docker-setup.sh"], cwd=openclaw_dir, env=env, check=True)
                    else:
                        subprocess.run(["docker", "build", "-t", "openclaw:local", "."], cwd=openclaw_dir, check=True)
                    build_success = True
                    ok("OpenClaw 鏡像構建成功。")
                except Exception as e:
                    err(f"鏡像構建失敗：{e}")
            
            if not build_success:
                info("本地構建失敗或缺少 Dockerfile，嘗試從 GitHub Container Registry 拉取官方鏡像作為替代 (ghcr.io/openclaw/openclaw:latest)...")
                try:
                    # 拉取官方鏡像並重新標記為 openclaw:local 以匹配 compose 文件
                    subprocess.run(["docker", "pull", "ghcr.io/openclaw/openclaw:latest"], check=True)
                    subprocess.run(["docker", "tag", "ghcr.io/openclaw/openclaw:latest", "openclaw:local"], check=True)
                    ok("成功獲取官方 OpenClaw 鏡像並標記為 local。")
                except Exception as e:
                    err(f"拉取官方鏡像也失敗了：{e}")

        info("啟動 OpenClaw 容器…")
        try:
            subprocess.run(
                compose_cmd + ["up", "-d", "--remove-orphans"],
                cwd=openclaw_dir,
                env=env, # 使用 get_openclaw_env 產出的 env
                check=True
            )
            ok("OpenClaw 已就緒！")
        except subprocess.CalledProcessError as exc:
            err(f"OpenClaw 啟動失敗：{exc}")
            # 不阻擋後續

    # ── 安裝相依套件 ───────────────────────────────────────────────────────
    info("檢查並安裝專案相依套件 (pip install -e .) ...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
    
    # 偵測是否需要 --break-system-packages (針對 Kali/Debian 外部管理環境)
    if system == "Linux":
        try:
            # 測試是否會報錯
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--help"], capture_output=True, text=True)
            if "--break-system-packages" in r.stdout:
                info("檢測到 Linux 外部管理環境，自動加入 --break-system-packages")
                pip_cmd.append("--break-system-packages")
        except Exception:
            pass

    try:
        subprocess.run(
            pip_cmd,
            cwd=PROJECT_ROOT,
            check=True
        )
        ok("相依套件安裝完成！")
    except subprocess.CalledProcessError as exc:
        err(f"相依套件安裝失敗：{exc}")
        sys.exit(1)

    # ── 原生啟動 openSOUL API ───────────────────────────────────────────────
    info("原生啟動 openSOUL API...")
    env_api = os.environ.copy()
    env_api["FALKORDB_HOST"] = "localhost"  # Ensure it points to local forwarded port
    
    pid_file = PROJECT_ROOT / ".uvicorn.pid"
    log_file_path = PROJECT_ROOT / "uvicorn.log"
    
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
        
    try:
        ok("openSOUL API 準備就緒！")
        print_next_steps()
        info("正在啟動 API (按 Ctrl+C 停止)...")
        api_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "soul.interface.api:app", "--host", "0.0.0.0", "--port", "8002"],
            cwd=PROJECT_ROOT,
            env=env_api
        )
        pid_file.write_text(str(api_process.pid), encoding="utf-8")
        
        # 讓它留在前景執行，阻擋腳本退出，這樣使用者就能直接看到 log
        api_process.wait()
    except KeyboardInterrupt:
        info("接收到中斷訊號，正在關閉 API...")
    except Exception as e:
        err(f"啟動 API 失敗：{e}")
    finally:
        if 'api_process' in locals() and api_process.poll() is None:
            api_process.terminate()
            api_process.wait()
    
    print_next_steps()


def action_stop(compose_cmd: list[str]) -> None:
    """停止 FalkorDB 與 OpenClaw 服務（保留容器與 Volume，更安全）。"""
    # 首先清理佔用的端口
    cleanup_api_port(port=8002)

    info("停止 FalkorDB 服務…")
    # 先強制存檔，確保記憶體中的圖譜資料寫入磁碟 (持久化最關鍵一步)
    try:
        # 使用 redis-cli SAVE (同步存檔) 而非 BGSAVE (非同步)，確保存檔完成才往下走
        subprocess.run(
            ["docker", "exec", "opensoul-falkordb", "redis-cli", "-p", "6379", "SAVE"],
            check=False, capture_output=True,
        )
        ok("資料庫已成功同步存檔。")
    except Exception:
        pass  # 容器可能已停止，忽略錯誤

    try:
        # 使用 stop 而非 down，避免移除容器，確保資料狀態完整保留
        subprocess.run(
            compose_cmd + ["-f", str(COMPOSE_FILE), "stop"],
            check=True,
            cwd=PROJECT_ROOT,
        )
        ok("FalkorDB 已停止。（數據與狀態完全保留）")
    except subprocess.CalledProcessError as exc:
        warn(f"docker compose stop 失敗（可能 Docker 已關閉）：{exc}")
        # 不中斷執行，嘗試停止其他服務
        
    openclaw_dir = PROJECT_ROOT / "openclaw"
    if openclaw_dir.exists() and (openclaw_dir / "docker-compose.yml").exists():
        info("停止 OpenClaw 服務…")
        try:
            # 必須傳入相同的環境變數，否則 Compose 會因為變數未解析而報錯
            env = get_openclaw_env()
            subprocess.run(
                compose_cmd + ["-f", "docker-compose.yml", "stop"],
                check=True,
                cwd=openclaw_dir,
                env=env,
            )
            ok("OpenClaw 已停止。")
        except subprocess.CalledProcessError as exc:
            warn(f"OpenClaw 停止失敗（可能 Docker 已關閉）：{exc}")

    info("停止原生 openSOUL API...")
    pid_file = PROJECT_ROOT / ".uvicorn.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
            ok(f"已停止 API 進程 (PID: {pid})")
        except Exception as e:
            err(f"無法停止 openSOUL API：{e}")
        finally:
            pid_file.unlink(missing_ok=True)
    else:
        info("找不到 openSOUL API 的執行紀錄 (.uvicorn.pid)，跳過。")


def action_status() -> None:
    """顯示容器狀態與服務連通性。"""
    falkordb_up  = check_port(FALKORDB_HOST, FALKORDB_PORT)
    browser_up   = check_port(FALKORDB_HOST, 3000)
    api_up       = check_port("localhost", 8002)

    if HAS_RICH:
        table = Table(title="openSOUL 服務狀態", show_header=True, header_style="bold cyan")
        table.add_column("服務", style="white")
        table.add_column("位址", style="dim")
        table.add_column("狀態", justify="center")

        def status_cell(up: bool) -> str:
            return "[green]● 運行中[/green]" if up else "[red]○ 未啟動[/red]"

        table.add_row("FalkorDB",           f"{FALKORDB_HOST}:{FALKORDB_PORT}", status_cell(falkordb_up))
        table.add_row("FalkorDB Browser",   f"{FALKORDB_HOST}:3000",            status_cell(browser_up))
        table.add_row("openSOUL API",       "localhost:8002",                   status_cell(api_up))
        console.print(table)
    else:
        print(f"\nFalkorDB  ({FALKORDB_HOST}:{FALKORDB_PORT}): {'✓ UP' if falkordb_up else '✗ DOWN'}")
        print(f"FalkorDB Browser (3000):       {'✓ UP' if browser_up else '✗ DOWN'}")
        print(f"openSOUL API     (8002):       {'✓ UP' if api_up else '✗ DOWN'}")


def print_next_steps() -> None:
    msg = (
        "[bold]接下來：[/bold]\n"
        "  1. 開啟瀏覽器（openSOUL 互動 UI）：\n"
        "     [cyan]http://localhost:8002[/cyan]\n\n"
        "  2. 圖譜記憶檢視器（FalkorDB Browser）：\n"
        "     [cyan]http://localhost:3000[/cyan]\n\n"
        "  3. 監看伺服器日誌（方便除錯）：\n"
        "     [cyan]Get-Content -Wait -Tail 100 uvicorn.log[/cyan] (Windows) ← openSOUL API 日誌\n"
        "     [cyan]tail -f uvicorn.log[/cyan] (Mac/Linux)               ← openSOUL API 日誌\n"
        "     [cyan]docker logs -f openclaw-openclaw-cli-1[/cyan]          ← OpenClaw AI 決策日誌\n\n"
        "  4. 停止所有服務：\n"
        "     [cyan]python scripts/setup_env.py --stop[/cyan]"
    ).format(root=PROJECT_ROOT)

    if HAS_RICH:
        console.print(Panel(msg, title="[green]環境就緒[/green]", border_style="green"))
    else:
        print("\n--- 接下來 ---")
        # strip rich markup for plain output
        import re
        print(re.sub(r"\[.*?\]", "", msg))


def print_install_guide(system: str, arch: str) -> None:
    """Docker 未安裝時印出安裝指引。"""
    url = INSTALL_URLS.get((system, arch), "https://docs.docker.com/get-docker/")

    # 偵測是否為 Kali Linux
    is_kali = False
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", "r") as f:
                if "kali" in f.read().lower():
                    is_kali = True
    except Exception:
        pass

    if system == "Linux":
        if is_kali:
            cmd_hint = (
                "  # [Kali Linux 專用] 修正 Docker 儲存庫並安裝\n"
                "  sudo apt-get update && sudo apt-get install -y curl gpg\n"
                "  sudo install -m 0755 -d /etc/apt/keyrings\n"
                "  curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg\n"
                "  sudo chmod a+r /etc/apt/keyrings/docker.gpg\n"
                "  echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null\n"
                "  sudo apt-get update\n"
                "  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin\n"
                "  sudo systemctl enable --now docker\n"
                "  sudo usermod -aG docker $USER\n"
                "  # 完成後請『重新登入』以生效"
            )
        else:
            cmd_hint = (
                "  # 快速安裝（Ubuntu / Debian / CentOS 等）\n"
                "  curl -fsSL https://get.docker.com | sh\n"
                "  sudo systemctl enable --now docker\n"
                "  sudo usermod -aG docker $USER  # 讓目前使用者免 sudo\n"
                "  # 登出後重新登入生效"
            )
    elif system == "Darwin":
        arch_name = "Apple Silicon (M 系列)" if arch == "arm64" else "Intel Mac"
        cmd_hint = f"  # 下載 Docker Desktop for {arch_name}：\n  {url}"
    else:
        cmd_hint = f"  # 下載 Docker Desktop for Windows：\n  {url}"

    msg = (
        f"[bold red]未偵測到 Docker[/bold red]（OS: {system}, CPU: {arch}{', Distro: Kali' if is_kali else ''}）\n\n"
        f"[bold]安裝步驟：[/bold]\n{cmd_hint}\n\n"
        f"安裝完成後，重新執行：\n"
        f"  [cyan]python scripts/setup_env.py[/cyan]"
    )

    if HAS_RICH:
        console.print(Panel(msg, title="[red]需要安裝 Docker[/red]", border_style="red"))
    else:
        print(f"\n[需要安裝 Docker]\nOS: {system}, CPU: {arch}\n{url}\n")


# ── 進入點 ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="openSOUL 環境設定：自動偵測 OS + CPU，啟動 FalkorDB Docker 容器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stop",   action="store_true", help="停止並移除 FalkorDB 容器")
    parser.add_argument("--status", action="store_true", help="顯示各服務連通狀態")
    args = parser.parse_args()

    # ── 顯示環境資訊 ──────────────────────────────────────────────────────
    system, arch = detect_environment()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    header("openSOUL 環境設定")
    if HAS_RICH:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("[dim]作業系統[/dim]",  f"[white]{system}[/white]")
        table.add_row("[dim]CPU 架構[/dim]",  f"[white]{arch}[/white]")
        table.add_row("[dim]Python[/dim]",    f"[white]{py_ver}[/white]")
        table.add_row("[dim]專案路徑[/dim]",  f"[white]{PROJECT_ROOT}[/white]")
        console.print(table)
    else:
        print(f"  OS:      {system}")
        print(f"  CPU:     {arch}")
        print(f"  Python:  {py_ver}")
        print(f"  Project: {PROJECT_ROOT}")

    # ── --status 不需要 compose ────────────────────────────────────────────
    if args.status:
        action_status()
        return

    # ── 確認 docker-compose.yml 存在 ──────────────────────────────────────
    if not COMPOSE_FILE.exists():
        err(f"找不到 {COMPOSE_FILE}")
        err("請在專案根目錄執行此腳本。")
        sys.exit(1)

    # ── 偵測 Docker ───────────────────────────────────────────────────────
    info("偵測 Docker…")
    if not detect_docker():
        print_install_guide(system, arch)
        sys.exit(1)
    ok("Docker daemon 運行中")

    # ── 偵測 Docker Compose ───────────────────────────────────────────────
    compose_cmd = detect_compose()
    if compose_cmd is None:
        err("找不到 docker compose 或 docker-compose 命令。")
        err("請安裝 Docker Desktop 或手動安裝 Docker Compose Plugin。")
        sys.exit(1)
    ok(f"使用 Compose 命令：{' '.join(compose_cmd)}")

    # ── 執行動作 ─────────────────────────────────────────────────────────
    if args.stop:
        action_stop(compose_cmd)
    else:
        action_start(compose_cmd)


if __name__ == "__main__":
    main()
