#!/usr/bin/env python3
"""
scripts/dev_start.py

供 preview_start / .claude/launch.json 使用的開發伺服器啟動腳本。
1. 呼叫 setup_env.py 啟動 Docker 容器（FalkorDB + openSOUL API）
2. 持續跟蹤 opensoul-api 日誌（保持行程存活，方便監控輸出）

用法：
    python scripts/dev_start.py
"""

from __future__ import annotations
import subprocess
import sys
import time
import socket
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def wait_for_port(host: str, port: int, timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(1)
    return False


def main() -> None:
    # ── 1. 啟動容器 ──────────────────────────────────────────────────────────
    print("[dev_start] 執行 setup_env.py 啟動容器…", flush=True)
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "setup_env.py")],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print("[dev_start] setup_env.py 回傳非零，容器可能未正常啟動。", flush=True)

    # ── 2. 等待 API 就緒（port 8001）────────────────────────────────────────
    print("[dev_start] 等待 openSOUL API（localhost:8001）就緒…", flush=True)
    if wait_for_port("localhost", 8001):
        print("[dev_start] ✓ API 已就緒：http://localhost:8001", flush=True)
    else:
        print("[dev_start] ⚠ 等待逾時，請確認容器是否正常啟動。", flush=True)

    # ── 3. 持續跟蹤 API 容器日誌（保持行程存活）────────────────────────────
    print("[dev_start] 開始跟蹤 opensoul-api 日誌…（Ctrl+C 停止）", flush=True)
    try:
        subprocess.run(
            ["docker", "logs", "-f", "opensoul-api"],
            cwd=PROJECT_ROOT,
        )
    except KeyboardInterrupt:
        print("\n[dev_start] 已中止。", flush=True)


if __name__ == "__main__":
    main()
