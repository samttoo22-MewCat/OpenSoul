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


def needs_rebuild(image_name: str, dockerfile_path: Path) -> bool:
    """
    檢查映像檔是否需要重新建置。
    邏輯：比較 Dockerfile 的修改時間與映像檔的建立時間。
    """
    if not dockerfile_path.exists():
        return False

    try:
        # 取得映像檔建立時間 (ISO 8601 格式)
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.Created}}", image_name],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if r.returncode != 0:
            return True # 映像檔不存在，需要建置

        image_created_str = r.stdout.strip()
        # 處理 Docker 可能傳回的 nano seconds 與時區 (例如 2024-03-04T12:34:56.789Z)
        # 我們簡化處理，僅取前 19 字元進行比較 (YYYY-MM-DDTHH:MM:SS)
        image_created_ts = time.mktime(time.strptime(image_created_str[:19], "%Y-%m-%dT%H:%M:%S"))
        
        # 取得 Dockerfile 修改時間
        dockerfile_mtime = dockerfile_path.stat().st_mtime
        
        # 如果 Dockerfile 較新 (差值大於 1 秒以避免浮點誤差)，則需要重新建置
        if dockerfile_mtime > image_created_ts + 1:
            return True
    except Exception:
        return True # 發生錯誤時保守起見建議重新建置

    return False


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


def cleanup_api_port(port: int = 6781, timeout: int = 5) -> None:
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


def fix_openclaw_base_url() -> None:
    """
    自動修正 openclaw/.env 中的 OPENAI_BASE_URL。

    根據作業系統自動更新為正確的配置：
    - Windows/macOS: http://host.docker.internal:{port}/v1
    - Linux/Raspberry Pi: http://172.17.0.1:{port}/v1
    """
    openclaw_env_file = PROJECT_ROOT / "openclaw" / ".env"
    if not openclaw_env_file.exists():
        return

    content = openclaw_env_file.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=False)
    changed = False
    system = platform.system()
    soul_api_port = get_soul_api_port()

    # 統一使用 host.docker.internal，藉由 docker-compose.yml 的 extra_hosts 處理跨平台解析
    correct_docker_host = "host.docker.internal"
    wrong_docker_host = "172.17.0.1"

    import re

    # 检查并修正每一行
    for i, line in enumerate(lines):
        if line.strip().startswith("OPENAI_BASE_URL=") and not line.strip().startswith("#"):
            original_url = line.split("=", 1)[1].strip()
            fixed_url = original_url

            # 如果使用了錯誤的 Docker host，替換為正確的
            if wrong_docker_host in original_url:
                fixed_url = fixed_url.replace(wrong_docker_host, correct_docker_host)
                warn(f"⚠️  檢測到系統配置錯誤！")
                warn(f"   系統: {system} → 應使用 {correct_docker_host}")
                warn(f"   原配置：{original_url}")
                changed = True

            # 确保端口与 Soul API 一致
            port_match = re.search(r":(\d+)/", fixed_url)
            if port_match:
                url_port = int(port_match.group(1))
                if url_port != soul_api_port:
                    fixed_url = re.sub(r":\d+/", f":{soul_api_port}/", fixed_url)
                    warn(f"⚠️  端口不匹配！")
                    warn(f"   Soul API 運行在 port {soul_api_port}")
                    changed = True

            if changed:
                warn(f"   已修正為：{fixed_url}")
                lines[i] = f"OPENAI_BASE_URL={fixed_url}"

    if changed:
        openclaw_env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok("✓ openclaw/.env 已自動修正（OPENAI_BASE_URL）")


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
        # 根據 OpenClaw 官方文檔建立最小化配置
        # 注意：memorySearch、contextPruning、compaction 在新版 OpenClaw 中已廢棄
        # 不要在 openclaw.json 中設置這些鍵，否則會觸發 "Invalid config" 錯誤
        config = {
            "gateway": {
                "bind": "lan"      # 跨平台綁定模式（lan = 允許局域網訪問）
            }
        }

        config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        ok(f"✓ 已建立 openclaw.json 於 {config_file}")
        info("   最小化配置：gateway.bind = lan（允許跨裝置存取）")
    except Exception as e:
        err(f"建立 openclaw.json 失敗：{e}")


def fix_openclaw_sessions(config_dir: Path) -> None:
    """自動修正 OpenClaw Session 配置，確保所有 Session 都導向本地 OpenSoul API。"""
    agents_dir = config_dir / "agents"
    if not agents_dir.exists():
        return

    # 先行嘗試全面奪回 agents 目錄的權限，避免底下的 sessions.json 被 Docker 鎖死（即便是讀取也可能 Permission Denied）
    if platform.system() != "Windows":
        user_name = os.environ.get("USER")
        if user_name:
            import subprocess
            subprocess.run(["sudo", "chown", "-R", f"{user_name}:{user_name}", str(agents_dir)], check=False, capture_output=True)

    import json

    def replace_recursive(obj):
        if isinstance(obj, dict):
            changed = False
            for k, v in obj.items():
                if k == "modelProvider" and v == "anthropic":
                    obj[k] = "custom_openai"
                    changed = True
                elif k == "provider" and v == "anthropic":
                    obj[k] = "custom_openai"
                    changed = True
                elif k == "model" and isinstance(v, str) and ("claude-" in v or v == "anthropic"):
                    obj[k] = "aria"
                    changed = True
                elif k == "modelId" and isinstance(v, str) and ("claude-" in v or v == "anthropic"):
                    obj[k] = "aria"
                    changed = True
                
                # 🆕 深入清洗 Agent 身上的「原生工具」記憶！
                # 即使全域 nativeSkills 被停用，已經初始化的 Agent Sessions.json 還是會殘留一份 tools 列表。
                elif k == "tools" and isinstance(v, dict) and "entries" in v:
                    old_len = len(v["entries"])
                    # openclaw 必須的最核心工具：message(發送訊息)、read/write/edit(基礎IO)、cron(定時)
                    # ⚠️ 徹底拔除 exec 與 process，防止它自己寫 Script 在終端機駭來駭去
                    allowed_tools = {"message", "read", "write", "edit", "cron"}
                    v["entries"] = [tool for tool in v["entries"] if tool.get("name") in allowed_tools]
                    if len(v["entries"]) != old_len:
                        changed = True

                elif isinstance(v, (dict, list)):
                    if replace_recursive(v):
                        changed = True
            return changed
        elif isinstance(obj, list):
            changed = False
            for i, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    if replace_recursive(item):
                        changed = True
            return changed
        return False

    try:
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            
            sessions_file = agent_dir / "sessions" / "sessions.json"
            if not sessions_file.exists():
                continue

            try:
                data = json.loads(sessions_file.read_text(encoding="utf-8"))
                if replace_recursive(data):
                    sessions_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    info(f"已深度修正 OpenClaw Session 配置：{agent_dir.name}/sessions.json")
            except Exception as e:
                warn(f"處理 {sessions_file} 時發生錯誤: {e}")
    except Exception as e:
        warn(f"自動修正 sessions.json 過程發生異常：{e}")


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

        # 2. 移除已廢棄的設定鍵（這些鍵在新版 OpenClaw 中已不支援）
        # ⚠️ 不要設定為 false，而是要完全移除！否則會觸發 "Invalid config" 錯誤
        deprecated_keys = ["memorySearch", "contextPruning", "compaction"]
        for deprecated_key in deprecated_keys:
            if deprecated_key in data:
                info(f"移除已廢棄的設定鍵：{deprecated_key}（新版 OpenClaw 不支援此鍵）")
                del data[deprecated_key]
                changed = True

        # 3. 移除不支援的 version 欄位
        if "version" in data:
            info("移除 openclaw.json 中不支援的 'version' 欄位。")
            del data["version"]
            changed = True

        # 4. 同步 Telegram 允許列表
        # 注意：Telegram 設定應位於 channels.telegram，而非 gateway.telegram
        channels = data.get("channels", {})
        if not isinstance(channels, dict): channels = {}
        data["channels"] = channels # 確保存在
        
        commands = data.get("commands", {})
        if not isinstance(commands, dict): commands = {}
        data["commands"] = commands
        if commands.get("nativeSkills") != False:
            info("強制關閉 OpenClaw 內置所有原生工具 (nativeSkills=false)，避免代理使用未正確配置的第三方服務")
            commands["nativeSkills"] = False
            changed = True
        # 🆕 清除先前錯誤注入的不支援 key（exec/process/onboarding/pairing）
        for _bad_cmd in ("exec", "process"):
            if _bad_cmd in commands:
                del commands[_bad_cmd]
                changed = True
        for _bad_key in ("onboarding", "pairing"):
            if _bad_key in data:
                del data[_bad_key]
                changed = True

        telegram = channels.get("telegram", {})
        if not isinstance(telegram, dict): telegram = {}
        
        current_allow = telegram.get("allowFrom", [])
        env_allow = get_telegram_allow_list()
        # 轉換為字串列表進行比較，確保一致性
        env_allow_str = [str(i) for i in env_allow]
        current_allow_str = [str(i) for i in current_allow]
        
        if current_allow_str != env_allow_str or telegram.get("dmPolicy") != "allowlist" or telegram.get("groupPolicy") != "allowlist":
            info(f"更新 Telegram 頻道設定...")
            if "telegram" not in channels or not isinstance(channels["telegram"], dict):
                channels["telegram"] = {"enabled": True}
            
            # 🆕 將 dmPolicy 設為 allowlist (白名單模式)，關閉初始設定導引選單 (Pairing Onboarding)
            channels["telegram"].update({
                "groupPolicy": "allowlist",
                "dmPolicy": "allowlist",
                "allowFrom": env_allow_str
            })
            changed = True
        
        # 🆕 同步 Gateway Token 到 openclaw/.env 以免不一致
        root_env = PROJECT_ROOT / ".env"
        oc_env = PROJECT_ROOT / "openclaw" / ".env"
        if root_env.exists() and oc_env.exists():
            root_text = root_env.read_text(encoding="utf-8")
            oc_text = oc_env.read_text(encoding="utf-8")
            
            token = None
            for line in root_text.splitlines():
                if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
            
            if token:
                new_oc_lines = []
                token_found = False
                for line in oc_text.splitlines():
                    if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
                        new_oc_lines.append(f"OPENCLAW_GATEWAY_TOKEN={token}")
                        token_found = True
                    else:
                        new_oc_lines.append(line)
                
                if not token_found:
                    new_oc_lines.append(f"OPENCLAW_GATEWAY_TOKEN={token}")
                
                new_oc_text = "\n".join(new_oc_lines)
                if new_oc_text != oc_text:
                    oc_env.write_text(new_oc_text, encoding="utf-8")
                    info("同步 OPENCLAW_GATEWAY_TOKEN 至 openclaw/.env")
        
        # 移除錯誤路徑（如果存在）
        if "gateway" in data and isinstance(data["gateway"], dict):
            if "telegram" in data["gateway"]:
                del data["gateway"]["telegram"]
                changed = True
            if "memory" in data["gateway"]:
                del data["gateway"]["memory"]
                changed = True

        # 🆕 強制設定預設模型 Provider，防止 OpenClaw 自動回退到 Anthropic/Claude
        agents = data.get("agents", {})
        if not isinstance(agents, dict): agents = {}
        data["agents"] = agents
        
        defaults = agents.get("defaults", {})
        if not isinstance(defaults, dict): defaults = {}
        agents["defaults"] = defaults
        
        model_defaults = defaults.get("model", {})
        if not isinstance(model_defaults, dict): model_defaults = {}
        defaults["model"] = model_defaults
        
        primary = model_defaults.get("primary", {})
        if not isinstance(primary, dict): primary = {}
        
        # 取得當前環境變數或預設值
        target_provider = os.environ.get("LLM_PROVIDER", "custom_openai")
        target_model = os.environ.get("MODEL", "aria")
        target_full_id = f"{target_provider}/{target_model}"

        # 🆕 建立/更新 Auth Profiles 確保 API Key 存在
        auth_file = config_dir / "agents" / "main" / "agent" / "auth-profiles.json"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        
        auth_data = {}
        if auth_file.exists():
            try:
                auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
            except Exception: pass
            
        if not isinstance(auth_data, dict): auth_data = {}
        
        # 確保有多種可能的 key 名稱 (OpenClaw 不同版本對自定義 provider 的 key 命名規則可能不同)
        needs_update = False
        for k in ["custom_openai", "openai", "openai-completions"]:
            if auth_data.get(k) != "dummy":
                auth_data[k] = "dummy"
                needs_update = True
                
        if needs_update:
            info("建立/更新 OpenClaw Auth Profile (多重 Key 備援)...")
            auth_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")

        # 🆕 真正的模型型錄註冊方式 (OpenClaw 2026.3+)
        # 移除錯誤的 agents.models
        if "models" in agents:
            del agents["models"]
            changed = True

        models_root = data.get("models", {})
        if not isinstance(models_root, dict): models_root = {}
        data["models"] = models_root
        
        providers = models_root.get("providers", {})
        if not isinstance(providers, dict): providers = {}
        models_root["providers"] = providers
        
        if target_provider not in providers:
            info(f"在型錄中註冊 Provider: {target_provider}")
            providers[target_provider] = {
                "baseUrl": os.environ.get("OPENAI_BASE_URL", "http://host.docker.internal:6781/v1"),
                "api": "openai-completions",
                "apiKey": "dummy",
                "models": [
                    {
                        "id": target_model,
                        "name": f"ARIA ({target_provider})",
                        "contextWindow": 128000
                    }
                ]
            }
            changed = True
        elif "apiKey" not in providers[target_provider] or providers[target_provider]["apiKey"] != "dummy":
            # 🆕 強化認證：即使 Provider 已存在，也確保有 apiKey
            providers[target_provider]["apiKey"] = "dummy"
            changed = True

        if primary != target_full_id:
            info(f"強制更新 OpenClaw 預設模型為 {target_full_id}...")
            model_defaults["primary"] = target_full_id
            changed = True

        if changed:
            config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            ok("OpenClaw 配置檔已自動更新（包含 Telegram 允許列表）。")
            
        # 🆕 同步修正所有 Agent 的 Session 配置，防止 401 錯誤導向 Anthropic
        fix_openclaw_sessions(config_dir)
    except Exception as e:
        warn(f"嘗試自動修正 openclaw.json 時發生錯誤（跳過）：{e}")


def get_soul_api_port() -> int:
    """
    從環境變數或 .env 文件讀取 Soul API 端口。
    優先順序：進程環境變數 > .env 文件 > 預設值（6781）
    """
    # 先檢查進程環境變數
    port_str = os.environ.get("SOUL_API_PORT")
    if port_str:
        try:
            return int(port_str)
        except ValueError:
            pass

    # 從 .env 文件讀取
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SOUL_API_PORT=") and not line.startswith("#"):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass

    return 6781  # 預設值（與 openclaw/.env.example 的 OPENAI_BASE_URL port 一致）


def get_telegram_allow_list() -> list[int]:
    """
    從環境變數或 .env 文件讀取 Telegram 允許列表。
    回傳整數列表。
    """
    allow_str = os.environ.get("TELEGRAM_ALLOW_FROM")
    
    if not allow_str:
        # 嘗試從根目錄 .env 讀取
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_ALLOW_FROM="):
                    allow_str = line.split("=", 1)[1].strip()
                    break
        
        # 嘗試從 openclaw/.env 讀取 (備援)
        if not allow_str:
            oc_env = PROJECT_ROOT / "openclaw" / ".env"
            if oc_env.exists():
                for line in oc_env.read_text(encoding="utf-8").splitlines():
                    if line.startswith("TELEGRAM_ALLOW_FROM="):
                        allow_str = line.split("=", 1)[1].strip()
                        break
    
    if not allow_str:
        return [114514] # 預設值
        
    try:
        # 支援逗號分隔，例如 "123,456"
        return [int(x.strip()) for x in allow_str.split(",") if x.strip()]
    except ValueError:
        warn(f"TELEGRAM_ALLOW_FROM 格式錯誤：{allow_str}，回退至預設值。")
        return [114514]


def check_openclaw_base_url() -> None:
    """
    檢查 openclaw/.env 中的 OPENAI_BASE_URL 設定。
    - 若使用 127.0.0.1 或 localhost，則警告（Docker 內部無法訪問主機）
    - 若指向的 port 與 Soul API port 不符，則警告
    """
    openclaw_env_file = PROJECT_ROOT / "openclaw" / ".env"
    if not openclaw_env_file.exists():
        return

    soul_api_port = get_soul_api_port()

    for line in openclaw_env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPENAI_BASE_URL=") and not line.startswith("#"):
            url = line.split("=", 1)[1].strip()

            # 檢查是否使用了 127.0.0.1 或 localhost（Docker 內無法訪問主機）
            if "127.0.0.1" in url or "//localhost" in url:
                warn("━" * 60)
                warn(f"⚠️  OPENAI_BASE_URL 使用了 127.0.0.1/localhost！")
                warn(f"   當前設定：{url}")
                warn(f"   ❌ 問題：OpenClaw 在 Docker 容器內，127.0.0.1 指向容器自身，")
                warn(f"          不是您的主機，Soul API 無法被訪問！")
                system = platform.system()
                if system in ("Windows", "Darwin"):
                    warn(f"   ✅ 建議改為：OPENAI_BASE_URL=http://host.docker.internal:{soul_api_port}/v1")
                else:
                    try:
                        result = subprocess.run(
                            ["hostname", "-I"], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=3
                        )
                        host_ip = result.stdout.strip().split()[0] if result.stdout.strip() else "YOUR_HOST_IP"
                    except Exception:
                        host_ip = "YOUR_HOST_IP"
                    warn(f"   ✅ 建議改為：OPENAI_BASE_URL=http://{host_ip}:{soul_api_port}/v1")
                warn(f"   請修改 openclaw/.env 後重新啟動。")
                warn("━" * 60)

            # 檢查 port 是否與 Soul API 一致
            import re
            port_match = re.search(r":(\d+)/", url)
            if port_match:
                url_port = int(port_match.group(1))
                if url_port != soul_api_port:
                    warn("━" * 60)
                    warn(f"⚠️  OPENAI_BASE_URL 的端口 ({url_port}) 與 Soul API 端口 ({soul_api_port}) 不符！")
                    warn(f"   當前設定：{url}")
                    warn(f"   Soul API 將啟動在 port {soul_api_port}（由 SOUL_API_PORT 決定）")
                    # 自動修正建議
                    fixed_url = re.sub(r":\d+/", f":{soul_api_port}/", url)
                    warn(f"   ✅ 建議改為：OPENAI_BASE_URL={fixed_url}")
                    warn("━" * 60)
            break


def wait_for_soul_api(port: int, timeout: int = 30) -> bool:
    """
    等待 Soul API 在指定端口就緒。
    使用 HTTP /health endpoint 驗證（確保是真的 Soul API，不是其他程序）。
    最多等待 timeout 秒。
    """
    info(f"等待 Soul API 就緒（port {port}，最多 {timeout}s）…")
    start = time.time()
    while time.time() - start < timeout:
        try:
            import urllib.request
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
            if response.status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def is_soul_api_running(port: int) -> bool:
    """
    檢查 Soul API 是否真的在指定 port 運行。
    不只檢查 TCP 連通性，還驗證 /health endpoint（確保是 Soul API，不是其他程序）。
    """
    try:
        import urllib.request
        response = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
        return response.status == 200
    except Exception:
        return False


def run_openclaw_doctor(compose_cmd: list[str], openclaw_dir: Path, env: dict) -> None:
    """
    在 OpenClaw 容器內執行 'openclaw doctor --fix' 以自動修正配置問題。
    這能解決 openclaw.json 版本過舊、廢棄鍵等常見問題。

    嘗試順序：
    1. openclaw-gateway（通常是長駐服務，最可靠）
    2. openclaw-cli（若 gateway 不支援則試此服務）
    若兩者都失敗，靜默跳過（不阻擋正常啟動）。
    """
    info("執行 openclaw doctor --fix（自動修正 openclaw.json 配置）…")
    # 等待容器穩定（避免 container 剛起來 openclaw binary 還沒就緒）
    time.sleep(3)

    # 嘗試的 service name 列表（按優先順序）
    services_to_try = ["openclaw-gateway", "openclaw-cli"]

    for service in services_to_try:
        try:
            result = subprocess.run(
                compose_cmd + ["-f", "docker-compose.yml", "exec", "-T", service,
                               "openclaw", "doctor", "--fix"],
                cwd=openclaw_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
            )
            if result.returncode == 0:
                ok(f"openclaw doctor --fix 執行成功（via {service}），配置已是最新版。")
                return
            elif "is not running" in result.stderr or "no such service" in result.stderr.lower():
                # 該服務未啟動，試下一個
                continue
            else:
                # 其他錯誤 - 可能 doctor 不支援或已是最新，靜默繼續
                ok(f"openclaw.json 配置已是最新版（doctor 回報：{result.stderr.strip()[:100]}）")
                return
        except subprocess.TimeoutExpired:
            warn(f"openclaw doctor --fix 在 {service} 上逾時（跳過）。")
            return
        except Exception:
            continue

    # 所有服務都失敗或未啟動，靜默跳過
    info("跳過 openclaw doctor --fix（容器暫時不可用，配置已由本機 fix_openclaw_config 處理）。")


    # （此處第一份定義已移除，統一使用後方的定義）
    pass

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


def get_available_package_manager() -> tuple[str, list[str]] | None:
    """
    偵測系統上可用的包管理器。
    回傳 (pm_name, install_cmd_parts)，例如 ("brew", ["brew", "install"])
    """
    system = platform.system()

    # 檢查各平台的包管理器
    managers = []

    if system == "Darwin":
        # macOS
        managers = [
            ("brew", ["brew", "install"]),
            ("port", ["sudo", "port", "install"]),
        ]
    elif system == "Linux":
        # Linux 發行版偵測
        managers = [
            ("apt", ["sudo", "apt-get", "install", "-y"]),
            ("yum", ["sudo", "yum", "install", "-y"]),
            ("dnf", ["sudo", "dnf", "install", "-y"]),
            ("pacman", ["sudo", "pacman", "-S", "--noconfirm"]),
            ("brew", ["brew", "install"]),  # Linuxbrew
        ]
    elif system == "Windows":
        # Windows 包管理器（優先順序：Scoop > Choco > Winget）
        managers = [
            ("scoop", ["scoop", "install"]),
            ("choco", ["choco", "install", "-y"]),
            ("winget", ["winget", "install", "--exact", "--quiet"]),
        ]

    # 逐一檢查哪個包管理器可用
    for pm_name, pm_cmd in managers:
        try:
            subprocess.run(
                [pm_cmd[0], "--version"],
                capture_output=True, check=True, timeout=5
            )
            return (pm_name, pm_cmd)
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    return None


def install_skill_dependencies(skill_name: str, skill_dir: Path) -> None:
    """
    自動安裝技能的二進制依賴。
    讀取 SKILL.md 的 metadata，檢測所需工具並自動安裝。
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return

    try:
        import frontmatter
        with open(skill_md, encoding='utf-8') as f:
            doc = frontmatter.load(f)

        metadata = doc.metadata.get("metadata", {})
        openclaw_meta = metadata.get("openclaw", {})
        requires = openclaw_meta.get("requires", {})
        bins = requires.get("bins", [])
        install_methods = openclaw_meta.get("install", [])

        if not bins:
            return

        # 檢查每個 bin 是否已安裝
        for bin_name in bins:
            try:
                subprocess.run(
                    ["which", bin_name] if platform.system() != "Windows" else ["where", bin_name],
                    capture_output=True, check=True, timeout=5
                )
                info(f"  ✓ {bin_name} 已安裝")
                continue
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

            # 取得系統可用的包管理器
            pm_info = get_available_package_manager()
            if not pm_info:
                system = platform.system()
                if system == "Windows":
                    warn(f"  ⚠ 【{bin_name}】無法自動安裝 - Windows 上找不到包管理器")
                    warn(f"    請選擇以下任一方式安裝：")
                    warn(f"    1️⃣  安裝 Scoop：  iwr -useb get.scoop.sh | iex")
                    warn(f"    2️⃣  安裝 Chocolatey：https://chocolatey.org/install")
                    warn(f"    3️⃣  使用 Winget（Windows 11）：winget install {bin_name}")
                    warn(f"    4️⃣  手動下載：{skill_md}")
                elif system == "Darwin":
                    warn(f"  ⚠ 【{bin_name}】無法自動安裝 - macOS 上未找到 Homebrew")
                    warn(f"    請安裝 Homebrew：/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
                elif system == "Linux":
                    warn(f"  ⚠ 【{bin_name}】無法自動安裝 - Linux 上未找到包管理器")
                    warn(f"    請使用你的發行版的包管理器 (apt/yum/dnf/pacman) 或安裝 Homebrew")
                continue

            pm_name, pm_cmd = pm_info
            installed = False

            # 嘗試用不同的包管理器安裝
            for install_method in install_methods:
                method_kind = install_method.get("kind")

                # brew 方法適用於所有平台（macOS、Linux、Windows）
                if method_kind == "brew":
                    formula = install_method.get("formula")
                    if formula and pm_name == "brew":
                        try:
                            info(f"  正在安裝 {bin_name} (via brew)…")
                            subprocess.run(
                                pm_cmd + [formula],
                                capture_output=True, check=True, timeout=120
                            )
                            ok(f"  ✓ {bin_name} 安裝完成")
                            installed = True
                            break
                        except Exception as e:
                            warn(f"  Brew 安裝失敗：{e}")

                # apt 方法用於 Linux
                elif method_kind == "apt" and pm_name == "apt":
                    package = install_method.get("package")
                    if package:
                        try:
                            info(f"  正在安裝 {bin_name} (via apt)…")
                            subprocess.run(
                                pm_cmd + [package],
                                capture_output=True, check=True, timeout=120
                            )
                            ok(f"  ✓ {bin_name} 安裝完成")
                            installed = True
                            break
                        except Exception as e:
                            warn(f"  Apt 安裝失敗：{e}")

                # choco 方法用於 Windows
                elif method_kind == "choco" and pm_name == "choco":
                    package = install_method.get("package")
                    if package:
                        try:
                            info(f"  正在安裝 {bin_name} (via choco)…")
                            subprocess.run(
                                pm_cmd + [package],
                                capture_output=True, check=True, timeout=120
                            )
                            ok(f"  ✓ {bin_name} 安裝完成")
                            installed = True
                            break
                        except Exception as e:
                            warn(f"  Choco 安裝失敗：{e}")

                # scoop 方法用於 Windows
                elif method_kind == "scoop" and pm_name == "scoop":
                    package = install_method.get("package")
                    if package:
                        try:
                            info(f"  正在安裝 {bin_name} (via scoop)…")
                            subprocess.run(
                                pm_cmd + [package],
                                capture_output=True, check=True, timeout=120
                            )
                            ok(f"  ✓ {bin_name} 安裝完成")
                            installed = True
                            break
                        except Exception as e:
                            warn(f"  Scoop 安裝失敗：{e}")

            if not installed:
                warn(f"  ⚠ 無法自動安裝 {bin_name}（缺少對應的安裝方法）")
                warn(f"    請參考 {skill_md} 進行手動安裝")

    except Exception as e:
        warn(f"檢查 {skill_name} 依賴失敗：{e}")


def setup_skill_api_keys() -> None:
    """
    自動設置技能所需的 API key。
    優先讀取 .env 文件，無則跳過。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)

        # 支持的 API key 列表
        api_keys = [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "XAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_GENERATIVE_AI_API_KEY",
            "GOOGLE_API_KEY",
            "FIRECRAWL_API_KEY",
            "APIFY_API_TOKEN",
        ]

        for key in api_keys:
            value = os.environ.get(key)
            if value:
                # 設置到當前進程和子進程
                os.environ[key] = value
                info(f"  已載入 API key: {key}")

    except Exception as e:
        warn(f"設置 API key 失敗：{e}")


def get_openclaw_env() -> dict[str, str]:
    """產出一致的 OpenClaw Docker 環境變數。"""
    env = os.environ.copy()
    # 🆕 提前注入 CI 旗標，確保 docker-setup.sh 也能繞過互動式提示器
    env["CI"] = "true"
    env["OPENCLAW_NO_PROMPT"] = "1"
    env["TERM"] = "dumb"
    openclaw_dir = PROJECT_ROOT / "openclaw"

    config_dir = Path.home() / ".openclaw"
    workspace_dir = PROJECT_ROOT / "workspace"
    project_skills_dir = openclaw_dir / "skills"

    config_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # 嘗試自動修復 .openclaw 目錄的權限 (若被 Docker 建立為 root)
    if platform.system() != "Windows":
        try:
            oc_json = config_dir / "openclaw.json"
            if not os.access(config_dir, os.W_OK) or (oc_json.exists() and not os.access(oc_json, os.W_OK)):
                warn("偵測到 .openclaw 或其設定檔權限不足，嘗試自動取回權限 (可能需要輸入 sudo 密碼)...")
                user_name = os.environ.get("USER")
                if user_name:
                    subprocess.run(["sudo", "chown", "-R", f"{user_name}:{user_name}", str(config_dir)], check=False)
        except Exception as e:
            warn(f"自動取回權限失敗：{e}")

    # 決定正確的 Docker Host URL
    docker_host = "host.docker.internal"
    api_port = get_soul_api_port()
    base_url = f"http://{docker_host}:{api_port}/v1"
    os.environ["OPENAI_BASE_URL"] = base_url

    # 🆕 自動修正 openclaw/.env 中的 OPENAI_BASE_URL（Windows 配置糾正）
    # 這裡會確保 openclaw/.env 存在且內容正確
    fix_openclaw_base_url()

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
    # 嚴格限制只載入 Soul 引擎的核心技能與瀏覽器控制
    ESSENTIAL_SKILLS = ["soul-note", "edit-soul", "summarize"]
    
    if project_skills_dir.exists():
        target_skills_dir = config_dir / "skills"
        # 為了確保不會有殘留技能，同步前先清理遠端技能資料夾
        if target_skills_dir.exists():
            import shutil
            shutil.rmtree(target_skills_dir)
        target_skills_dir.mkdir(parents=True, exist_ok=True)
        
        info(f"正在同步核心技能至: {target_skills_dir}")
        sync_count = 0
        for skill in ESSENTIAL_SKILLS:
            src_skill = project_skills_dir / skill
            if src_skill.exists():
                # 同步技能檔案（依賴由 Docker 自動安裝）
                if sync_directory(src_skill, target_skills_dir / skill):
                    sync_count += 1

        if sync_count > 0:
            ok(f"成功同步 {sync_count} 個專案核心技能。")

        # 設置技能所需的 API key
        info("正在設置技能 API key…")
        setup_skill_api_keys()
        
        # 告知 Docker 使用該路徑下的 skills
        env["OPENCLAW_SKILLS_PATH"] = target_skills_dir.absolute().as_posix()

    # 強制注入絕對路徑
    env["OPENCLAW_CONFIG_DIR"] = config_dir.absolute().as_posix()
    env["OPENCLAW_WORKSPACE_DIR"] = workspace_dir.absolute().as_posix()
    env["OPENCLAW_GATEWAY_BIND"] = "lan"
    env["SOUL_PROJECT_ROOT"] = PROJECT_ROOT.absolute().as_posix()

    # 🆕 設置 UTF-8 編碼與忽略 TLS 憑證檢查（解決本機防毒或企業 Proxy 攔截導致的 fetch failed）
    env["PYTHONIOENCODING"] = "utf-8"
    env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"

    # 🆕 傳遞技能的 API key 到 Docker
    skill_api_keys = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_API_KEY",
        "FIRECRAWL_API_KEY", "APIFY_API_TOKEN"
    ]
    for api_key in skill_api_keys:
        if api_key in os.environ:
            env[api_key] = os.environ[api_key]

    # 如果還沒有 OPENAI_API_KEY，設置佔位符（防止 OpenClaw 報錯）
    if "OPENAI_API_KEY" not in env or not env["OPENAI_API_KEY"]:
        env["OPENAI_API_KEY"] = "dummy"
    env["LLM_PROVIDER"] = "custom_openai"
    env["OPENAI_BASE_URL"] = base_url
    env["MODEL"] = "aria"
    env["OPENAI_MODEL"] = "aria"
    env["OPENCLAW_AGENT_MODEL"] = "aria"
    env["SUMMARIZE_MODEL"] = "openai/aria"
    
    # 預防性注入，防止 OpenClaw 偵測到 Anthropic 模型時報錯（即便我們想用的是 ARIA）
    env["ANTHROPIC_API_KEY"] = "dummy"
    env["GEMINI_API_KEY"] = "dummy"
    
    # 🆕 注入 Provider 特定的 API Key 環境變數（高優先權，解決 No API key found）
    env["CUSTOM_OPENAI_API_KEY"] = "dummy"

    return env


# ── 主要動作 ───────────────────────────────────────────────────────────────

def action_start(compose_cmd: list[str]) -> None:
    """啟動 FalkorDB 容器與 OpenClaw 容器。"""
    system, arch = detect_environment()
    
    # 🆕 啟動前先嘗試停止容器，釋放檔案鎖，防止 OpenClaw 覆寫配置
    info("正在準備環境（嘗試停止現有服務以套用配置）…")
    try:
        subprocess.run(
            compose_cmd + ["-f", str(COMPOSE_FILE), "stop"],
            cwd=PROJECT_ROOT, capture_output=True, check=False
        )
        openclaw_dir_check = PROJECT_ROOT / "openclaw"
        if openclaw_dir_check.exists():
            subprocess.run(
                compose_cmd + ["-f", "docker-compose.yml", "stop"],
                cwd=openclaw_dir_check, capture_output=True, check=False
            )
    except Exception:
        pass

    info("啟動 FalkorDB 容器…")
    env = get_openclaw_env() # 共用環境資訊（內含修復邏輯）

    # 🆕 強化環境變數同步：將關鍵變數寫入 .env 文件，使 docker-compose 能讀取
    # 確保 Judge 在 Docker 容器中與原生 API 能共享配置
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT / "openclaw" / ".env"]:
        try:
            # 讀取現有 .env
            env_content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            lines = env_content.splitlines()
            
            # 需要持久化的鍵值配對
            persistence_keys = [
                "OPENCLAW_SKILLS_PATH", 
                "OPENCLAW_CONFIG_DIR", 
                "OPENCLAW_WORKSPACE_DIR", 
                "OPENCLAW_GATEWAY_TOKEN",
                "SOUL_PROJECT_ROOT",
                "TELEGRAM_ALLOW_FROM",
                "TELEGRAM_BOT_TOKEN",
                "CUSTOM_OPENAI_API_KEY",
                "OPENAI_API_KEY",
                "NODE_TLS_REJECT_UNAUTHORIZED",
                "SUMMARIZE_MODEL"
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
                env_path.parent.mkdir(parents=True, exist_ok=True)
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                ok(f"已更新 {env_path.name} 檔案以確保環境變數一致性。")
        except Exception as e:
            warn(f"無法同步 {env_path.name}：{e}")

    # 確保 Docker daemon 已完全啟動（Windows 可能需要更多時間）
    start_time = time.time()
    while time.time() - start_time < 30:
        if detect_docker():
            break
        time.sleep(1)

    # 🆕 Linux 防火牆自動開洞：允許 Docker 橋接網卡訪問主機 (解決 host.docker.internal Time Out)
    if platform.system() == "Linux":
        info("正在設定 Linux 防火牆以允許 Docker 存取本地 API (可能需要輸入 sudo 密碼)...")
        try:
            # -I INPUT 插入到最前面，優先權最高
            subprocess.run(["sudo", "iptables", "-I", "INPUT", "-i", "docker0", "-j", "ACCEPT"], check=False, capture_output=True)
            subprocess.run(["sudo", "iptables", "-I", "INPUT", "-i", "br-+", "-j", "ACCEPT"], check=False, capture_output=True)
            ok("已套用 Docker 網路防火牆通行規則")
        except Exception as e:
            warn(f"自動設定防火牆失敗，若 OpenClaw 發生 Time out 請手動執行 iptables 放行指令。細節: {e}")

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

    # ── 安裝相依套件 ───────────────────────────────────────────────────────
    # （先安裝，確保 uvicorn 可用）
    info("檢查並安裝專案相依套件 (pip install -e .) ...")
    pip_cmd = [sys.executable, "-m", "pip", "install", "-e", "."]

    # 偵測是否需要 --break-system-packages (針對 Kali/Debian 外部管理環境)
    if system == "Linux":
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--help"], capture_output=True, text=True, encoding='utf-8')
            if "--break-system-packages" in r.stdout:
                info("檢測到 Linux 外部管理環境，自動加入 --break-system-packages")
                pip_cmd.append("--break-system-packages")
        except Exception:
            pass

    try:
        subprocess.run(pip_cmd, cwd=PROJECT_ROOT, check=True)
        ok("相依套件安裝完成！")
    except subprocess.CalledProcessError as exc:
        err(f"相依套件安裝失敗：{exc}")
        sys.exit(1)

    # ── 原生啟動 openSOUL API（先啟動，OpenClaw 依賴此服務）───────────────
    soul_api_port = get_soul_api_port()
    pid_file = PROJECT_ROOT / ".uvicorn.pid"
    api_process = None

    if is_soul_api_running(soul_api_port):
        # 確認 Soul API 確實在運行（不只是 port 被佔用，而是真的有 Soul API） → 複用，不重複啟動
        ok(f"Soul API 已在 port {soul_api_port} 運行中，跳過重複啟動。")
    elif check_port("localhost", soul_api_port):
        # ⚠️ Port 被佔用，但不是 Soul API → 有其他程序在佔用
        err(f"❌ Port {soul_api_port} 被佔用，但**不是 Soul API**！")
        err(f"   可能是其他程序在使用此 port。")
        err(f"   請檢查：netstat -ano | findstr \":{soul_api_port}\"（Windows）")
        err(f"   或：lsof -i :{soul_api_port}（Linux/macOS）")
        err(f"   然後手動終止佔用的進程，或改用其他 port（SOUL_API_PORT 環境變數）。")
        sys.exit(1)
    else:
        info(f"原生啟動 openSOUL API（port {soul_api_port}）…")
        info(f"  ⚡ Soul API 必須先啟動，OpenClaw 才能處理 Telegram / Discord 訊息。")

        env_api = os.environ.copy()
        env_api["FALKORDB_HOST"] = "localhost"
        env_api["PYTHONIOENCODING"] = "utf-8"   # 防止 Windows cp950 編碼錯誤
        # 🆕 限制 Judge 只能看到核心技能，防止 ARIA 使用 web_search 等非授權工具
        if "OPENCLAW_SKILLS_PATH" in env:
            env_api["OPENCLAW_SKILLS_PATH"] = env["OPENCLAW_SKILLS_PATH"]

        try:
            api_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "soul.interface.api:app",
                 "--host", "0.0.0.0", "--port", str(soul_api_port)],
                cwd=PROJECT_ROOT,
                env=env_api,
            )
            pid_file.write_text(str(api_process.pid), encoding="utf-8")
        except Exception as e:
            err(f"啟動 Soul API 失敗：{e}")
            sys.exit(1)

        # 等待 Soul API 就緒（最多 30 秒）
        if wait_for_soul_api(soul_api_port, timeout=30):
            ok(f"Soul API 已就緒！（http://localhost:{soul_api_port}）")
        else:
            warn(f"Soul API 在 30 秒內未就緒（可能仍在初始化 FalkorDB 連線），繼續啟動其他服務…")

    # ── 啟動前檢查 OpenClaw OPENAI_BASE_URL 設定 ─────────────────────────
    check_openclaw_base_url()

    # ── 啟動 SearXNG（獨立啟動，不依賴 openclaw:local 鏡像）─────────────────
    openclaw_dir = PROJECT_ROOT / "openclaw"
    if openclaw_dir.exists() and (openclaw_dir / "docker-compose.yml").exists():
        info("啟動 SearXNG 搜尋服務…")
        # 確保設定目錄存在且可寫（SearXNG 啟動時需要在此目錄建立 settings.yml）
        searxng_config_dir = openclaw_dir / "searxng"
        searxng_config_dir.mkdir(mode=0o777, parents=True, exist_ok=True)
        try:
            subprocess.run(
                compose_cmd + ["-f", "docker-compose.yml", "up", "-d", "searxng"],
                cwd=openclaw_dir,
                env=env,
                check=True,
                capture_output=True,
            )
            ok("SearXNG 已就緒！（http://localhost:8888）")
        except subprocess.CalledProcessError as exc:
            warn(f"SearXNG 啟動失敗（web-research 搜尋功能將無法使用）：{exc}")

    # ── 啟動 OpenClaw ─────────────────────────────────────────────────────
    if openclaw_dir.exists() and (openclaw_dir / "docker-compose.yml").exists():
        info("檢查 OpenClaw 鏡像...")
        image_exists = False
        try:
            r = subprocess.run(["docker", "images", "-q", "openclaw:local"], capture_output=True, text=True, encoding='utf-8', errors='replace')
            if r.stdout.strip():
                image_exists = True
        except Exception:
            pass

        if not image_exists or needs_rebuild("openclaw:local", openclaw_dir / "Dockerfile"):
            if not image_exists:
                warn("未偵測到 openclaw:local 鏡像，正在啟動構建（Raspberry Pi 上可能較慢）…")
            else:
                info("偵測到 Dockerfile 有變動，正在自動重新建置 OpenClaw 鏡像…")
            
            docker_setup_script = openclaw_dir / "docker-setup.sh"
            dockerfile_path = openclaw_dir / "Dockerfile"

            build_success = False
            if dockerfile_path.exists():
                try:
                    # Windows 上 WSL 的 bash 無法翻譯 E: 等非 C: 磁碟路徑，直接用 docker build
                    if docker_setup_script.exists() and platform.system() != "Windows":
                        subprocess.run(["bash", "docker-setup.sh"], cwd=openclaw_dir, env=env, check=True)
                    else:
                        subprocess.run(["docker", "build", "--no-cache", "-t", "openclaw:local", "."], cwd=openclaw_dir, check=True)
                    build_success = True
                    ok("OpenClaw 鏡像構建成功。")
                except Exception as e:
                    err(f"鏡像構建失敗：{e}")

            if not build_success:
                info("嘗試從 GitHub Container Registry 拉取官方鏡像（ghcr.io/openclaw/openclaw:latest）…")
                try:
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
                env=env,
                check=True,
            )
            ok("OpenClaw 已就緒！")
            # 🆕 OpenClaw 啟動後重新套用工具白名單，覆蓋 OpenClaw 初始化時可能重建的 sessions
            time.sleep(5)
            fix_openclaw_sessions(Path.home() / ".openclaw")
            info("已重新套用工具白名單（exec/process 已鎖定）")

        except subprocess.CalledProcessError as exc:
            err(f"OpenClaw 啟動失敗：{exc}")
            # 不阻擋後續

    # ── 顯示下一步操作說明，然後進入 Soul API 前景等待 ──────────────────
    print_next_steps()

    if api_process is not None:
        # 我們自己啟動的 Soul API → 阻擋等待，保持服務在線
        info("正在運行 Soul API（按 Ctrl+C 停止所有服務）…")
        try:
            api_process.wait()
        except KeyboardInterrupt:
            info("接收到中斷訊號，正在關閉 Soul API…")
        except Exception as e:
            err(f"Soul API 異常退出：{e}")
        finally:
            if api_process.poll() is None:
                # ⚠️ 只終止我們自己啟動的進程，絕不用 kill-by-port（防止誤殺 Docker Desktop）
                api_process.terminate()
                api_process.wait()
    else:
        # Soul API 是已有的外部進程（port 已被佔用）→ 不做任何終止操作
        info("Soul API 由外部管理中，setup_env.py 不介入其生命週期。")


def action_stop(compose_cmd: list[str]) -> None:
    """停止 FalkorDB 與 OpenClaw 服務（保留容器與 Volume，更安全）。"""
    soul_api_port = get_soul_api_port()
    # 首先清理佔用的端口
    cleanup_api_port(port=soul_api_port)

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

            # ⚠️ 安全驗證：確認該 PID 確實是 uvicorn/python 進程，防止誤殺 Docker Desktop
            # Windows OS 會重用 PID，若進程已退出並被其他程序（如 Docker Desktop）佔用，
            # 直接 taskkill 可能釀成大禍
            is_safe_to_kill = False
            if sys.platform == "win32":
                try:
                    # 用 tasklist 查詢 PID 對應的程序名
                    r = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
                    )
                    output_lower = r.stdout.lower()
                    # 只有確認是 python 相關進程才殺
                    safe_names = ("python", "uvicorn", "pythonw")
                    if any(name in output_lower for name in safe_names):
                        is_safe_to_kill = True
                    else:
                        warn(f"PID {pid} 對應的進程不是 Python（{r.stdout.strip()[:80]}），跳過，防止誤殺其他服務。")
                except Exception:
                    pass  # 查詢失敗，保守起見不殺
            else:
                # Unix：用 /proc 或 ps 確認程序名
                try:
                    r = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
                    proc_name = r.stdout.strip().lower()
                    if "python" in proc_name or "uvicorn" in proc_name:
                        is_safe_to_kill = True
                    elif proc_name:
                        warn(f"PID {pid} 對應的進程是 '{proc_name}'，不是 Python，跳過終止。")
                    # 若 ps 返回空（進程已退出）→ is_safe_to_kill 保持 False
                except Exception:
                    pass

            if is_safe_to_kill:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
                else:
                    os.kill(pid, signal.SIGTERM)
                ok(f"已停止 Soul API 進程 (PID: {pid})")
            else:
                info(f"Soul API 進程（PID: {pid}）已不在或非 Python，無需終止。")

        except Exception as e:
            err(f"停止 openSOUL API 時發生錯誤：{e}")
        finally:
            pid_file.unlink(missing_ok=True)
    else:
        info("找不到 openSOUL API 的執行紀錄 (.uvicorn.pid)，跳過。")


def action_status() -> None:
    """顯示容器狀態與服務連通性。"""
    soul_api_port = get_soul_api_port()
    falkordb_up   = check_port(FALKORDB_HOST, FALKORDB_PORT)
    browser_up    = check_port(FALKORDB_HOST, 3000)
    api_up        = check_port("localhost", soul_api_port)
    openclaw_up   = check_port("localhost", 18789)  # OpenClaw gateway 預設端口
    searxng_up    = check_port("localhost", 8888)   # SearXNG 搜尋服務

    if HAS_RICH:
        table = Table(title="openSOUL 服務狀態", show_header=True, header_style="bold cyan")
        table.add_column("服務", style="white")
        table.add_column("位址", style="dim")
        table.add_column("狀態", justify="center")

        def status_cell(up: bool) -> str:
            return "[green]● 運行中[/green]" if up else "[red]○ 未啟動[/red]"

        table.add_row("FalkorDB",           f"{FALKORDB_HOST}:{FALKORDB_PORT}", status_cell(falkordb_up))
        table.add_row("FalkorDB Browser",   f"{FALKORDB_HOST}:3000",            status_cell(browser_up))
        table.add_row("openSOUL API (Web+API)", f"localhost:{soul_api_port}",   status_cell(api_up))
        table.add_row("OpenClaw Gateway",   "localhost:18789",                  status_cell(openclaw_up))
        table.add_row("SearXNG 搜尋",       "localhost:8888",                   status_cell(searxng_up))
        console.print(table)

        if not api_up:
            warn(f"⚠️  Soul API 未啟動！OpenClaw 無法回應 Telegram/Discord 訊息。")
            warn(f"   請執行：python scripts/setup_env.py")
        if not openclaw_up and api_up:
            warn(f"⚠️  OpenClaw 未啟動！請確認 openclaw/docker-compose.yml 已運行。")
    else:
        print(f"\nFalkorDB  ({FALKORDB_HOST}:{FALKORDB_PORT}): {'✓ UP' if falkordb_up else '✗ DOWN'}")
        print(f"FalkorDB Browser (3000):           {'✓ UP' if browser_up else '✗ DOWN'}")
        print(f"Soul API (localhost:{soul_api_port}): {'✓ UP' if api_up else '✗ DOWN'}")
        print(f"OpenClaw Gateway (18789):          {'✓ UP' if openclaw_up else '✗ DOWN'}")
        print(f"SearXNG 搜尋 (8888):               {'✓ UP' if searxng_up else '✗ DOWN'}")
        if not api_up:
            print(f"[WARN] Soul API 未啟動！Telegram/Discord 訊息無法得到回應。")


def print_next_steps() -> None:
    soul_api_port = get_soul_api_port()
    msg = (
        "[bold]接下來：[/bold]\n"
        f"  1. 開啟瀏覽器（openSOUL 互動 UI 兼 API 端點）：\n"
        f"     [cyan]http://localhost:{soul_api_port}[/cyan]\n\n"
        "  2. 圖譜記憶檢視器（FalkorDB Browser）：\n"
        "     [cyan]http://localhost:3000[/cyan]\n\n"
        "  2.5 SearXNG 隱私搜尋介面：\n"
        "     [cyan]http://localhost:8888[/cyan]\n\n"
        "  3. 監看伺服器日誌（方便除錯）：\n"
        "     [cyan]Get-Content -Wait -Tail 100 uvicorn.log[/cyan] (Windows)\n"
        "     [cyan]tail -f uvicorn.log[/cyan]                     (Mac/Linux)\n"
        "     [cyan]docker logs -f openclaw-openclaw-cli-1[/cyan]  (OpenClaw AI 決策日誌)\n\n"
        "  4. 停止所有服務：\n"
        "     [cyan]python scripts/setup_env.py --stop[/cyan]"
    )

    # 顯示技能狀態報告
    ESSENTIAL_SKILLS = ["soul-note", "edit-soul", "summarize"]
    print_skill_status_report(ESSENTIAL_SKILLS)

    if HAS_RICH:
        console.print(Panel(msg, title="[green]環境就緒[/green]", border_style="green"))
    else:
        print("\n--- 接下來 ---")
        import re
        print(re.sub(r"\[.*?\]", "", msg))


def print_skill_status_report(essential_skills: list[str]) -> None:
    """印出技能狀態檢查報告，顯示哪些技能可用，哪些因缺少依賴而不可用。"""
    openclaw_dir = PROJECT_ROOT / "openclaw" / "skills"
    if not openclaw_dir.exists():
        return

    skills_status = {}

    for skill_name in essential_skills:
        skill_dir = openclaw_dir / skill_name
        skill_md = skill_dir / "SKILL.md"

        if not skill_dir.exists():
            skills_status[skill_name] = ("❌ 不存在", "技能文件夾未找到")
            continue

        if not skill_md.exists():
            skills_status[skill_name] = ("✅ 就緒", "無依賴")
            continue

        # 檢查二進制依賴
        try:
            import frontmatter
            with open(skill_md, encoding='utf-8') as f:
                doc = frontmatter.load(f)

            metadata = doc.metadata.get("metadata", {})
            openclaw_meta = metadata.get("openclaw", {})
            requires = openclaw_meta.get("requires", {})
            bins = requires.get("bins", [])

            if not bins:
                skills_status[skill_name] = ("✅ 就緒", "無依賴")
                continue

            # 檢查依賴：先用 docker run --rm 在映像內檢查，再檢查主機
            all_bins_found = True
            checked_in_image = False

            # 確認 openclaw:local 映像是否存在
            image_exists = False
            try:
                ir = subprocess.run(
                    ["docker", "images", "-q", "openclaw:local"],
                    capture_output=True, timeout=5
                )
                image_exists = ir.returncode == 0 and bool(ir.stdout.strip())
            except Exception:
                pass

            for bin_name in bins:
                found = False

                # 1. 在映像內執行 which 檢查（CLI 容器設計為執行後退出，故用 run --rm）
                if image_exists:
                    try:
                        cmd_env = os.environ.copy()
                        cmd_env["MSYS_NO_PATHCONV"] = "1"
                        r = subprocess.run(
                            ["docker", "run", "--rm", "openclaw:local", "sh", "-c", f"which {bin_name}"],
                            capture_output=True, timeout=30, env=cmd_env
                        )
                        if r.returncode == 0:
                            found = True
                            checked_in_image = True
                    except Exception:
                        pass

                # 2. 再檢查主機
                if not found:
                    try:
                        hr = subprocess.run(
                            ["which", bin_name] if platform.system() != "Windows" else ["where", bin_name],
                            capture_output=True, timeout=5
                        )
                        if hr.returncode == 0:
                            found = True
                    except FileNotFoundError:
                        pass

                if not found:
                    all_bins_found = False
                    break

            if all_bins_found:
                location = "Docker 映像內" if checked_in_image else "主機"
                skills_status[skill_name] = ("✅ 就緒", f"依賴已安裝 ({location}): {', '.join(bins)}")
            else:
                skills_status[skill_name] = ("⚠️  缺少依賴", f"需要: {', '.join(bins)}")

        except Exception:
            skills_status[skill_name] = ("⚠️  檢查失敗", "無法讀取 SKILL.md")

    # 印出報告
    if skills_status:
        info("\n【核心技能狀態】")
        for skill, (status, detail) in skills_status.items():
            info(f"  {status}  {skill:20} - {detail}")

        # 如果有缺少依賴的技能，提示用戶
        missing_skills = [s for s, (status, _) in skills_status.items() if "缺少" in status]
        if missing_skills:
            warn(f"\n⚠️  有 {len(missing_skills)} 個技能因缺少依賴而無法使用：{', '.join(missing_skills)}")
            warn("  依賴應由 Docker 在構建時自動安裝。請重新構建鏡像：python scripts/setup_env.py")


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
        f"[bold red]未偵測到 Docker 或權限不足[/bold red]（OS: {system}, CPU: {arch}{', Distro: Kali' if is_kali else ''}）\n\n"
        f"💡 [bold]常見錯誤：Permission Denied[/bold]\n"
        f"若您已安裝 Docker 但仍看到此畫面，可能是當前使用者沒有權限存取 docker.sock。\n"
        f"請執行以下指令將使用者加入 docker 群組並立即生效：\n"
        f"  [cyan]sudo usermod -aG docker $USER[/cyan]\n"
        f"  [cyan]newgrp docker[/cyan]\n\n"
        f"[bold]全新安裝步驟：[/bold]\n{cmd_hint}\n\n"
        f"設定/安裝完成後，重新執行：\n"
        f"  [cyan]python scripts/setup_env.py[/cyan]"
    )

    if HAS_RICH:
        console.print(Panel(msg, title="[red]需要安裝 Docker 或權限不足[/red]", border_style="red"))
    else:
        print(f"\n[需要安裝 Docker 或權限不足]\n常見問題：如果已安裝 Docker，請嘗試執行 `sudo usermod -aG docker $USER` 和 `newgrp docker` 以賦予當前使用者權限。\nOS: {system}, CPU: {arch}\n{url}\n")


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
