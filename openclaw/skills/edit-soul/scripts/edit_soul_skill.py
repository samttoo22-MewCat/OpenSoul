#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/edit_soul_skill.py

SOUL.md 編輯/讀取工具 - 供 Agent 調用以查詢或更新自己的 SOUL.md 設定檔。

用法：
  python scripts/edit_soul_skill.py read
  python scripts/edit_soul_skill.py append "新增的內容"
  python scripts/edit_soul_skill.py replace "完整的內容"
"""

import sys
import argparse
import io
import json
import urllib.request
from pathlib import Path

# 強制 UTF-8 輸出（解決 Windows 控制台編碼問題）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import os
env_root = os.environ.get("SOUL_PROJECT_ROOT")
if env_root:
    PROJECT_ROOT = Path(env_root)
else:
    PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
# 🚀 優先使用 workspace 目錄，並支援環境變數
SOUL_MD_PATH = PROJECT_ROOT / "workspace" / "SOUL.md"
if not SOUL_MD_PATH.exists():
    # 嘗試根目錄作為 fallback
    alt_path = PROJECT_ROOT / "SOUL.md"
    if alt_path.exists():
        SOUL_MD_PATH = alt_path

print(f"DEBUG: 自動定位 SOUL.md 於 {SOUL_MD_PATH.absolute()}", file=sys.stderr)

# 🚀 修正 API 埠號至 8002 (與 openSOUL 預設一致)
# 且在 Docker 內應存取 host.docker.internal 或環境變數定義的位址
API_PORT = 8002 
API_URL = f"http://localhost:{API_PORT}/soul" 

def trigger_reload(content: str):
    """呼叫 API 更新 SOUL.md 以讓核心立即重新載入。"""
    try:
        req = urllib.request.Request(API_URL, method="PUT")
        req.add_header("Content-Type", "application/json")
        data = json.dumps({"content": content}).encode("utf-8")
        with urllib.request.urlopen(req, data=data, timeout=3) as response:
            if response.status == 200:
                print("✅ 代理人內核同步重新載入成功。")
    except Exception as e:
        print(f"⚠️ 備註：本地檔案已儲存，但無法即時通知執行中的伺服器重新載入 ({e})。伺服器若未啟動可忽略此訊息。", file=sys.stderr)

def cmd_read(args):
    """讀取 SOUL.md。"""
    if SOUL_MD_PATH.exists():
        content = SOUL_MD_PATH.read_text(encoding="utf-8")
        print(content)
    else:
        print(f"❌ 找不到 SOUL.md 於 {SOUL_MD_PATH}", file=sys.stderr)

def cmd_append(args):
    """在 SOUL.md 最底層加入新內容。"""
    if not SOUL_MD_PATH.exists():
        print(f"❌ 找不到 SOUL.md 於 {SOUL_MD_PATH}", file=sys.stderr)
        return

    content = SOUL_MD_PATH.read_text(encoding="utf-8")
    # 清理結尾的換行符，確保格式整齊
    content = content.rstrip()
    new_content = f"{content}\n\n{args.text}\n"
    
    _save_and_reload(new_content)
    print("✅ 已成功附加內容至 SOUL.md。")

def cmd_replace(args):
    """直接替換整個 SOUL.md 檔案內容。"""
    _save_and_reload(args.text)
    print("✅ 已成功替換 SOUL.md 內容。")

def cmd_diff(args):
    """使用 old_string/new_string 精確替換 SOUL.md 部分內容（diff 模式）。"""
    if not SOUL_MD_PATH.exists():
        print(f"❌ 找不到 SOUL.md 於 {SOUL_MD_PATH}", file=sys.stderr)
        return 1

    content = SOUL_MD_PATH.read_text(encoding="utf-8")

    if args.old not in content:
        print("❌ 找不到指定的舊文字，請確認內容與 SOUL.md 完全一致（含空白、換行）", file=sys.stderr)
        return 1

    count = content.count(args.old)
    if count > 1:
        print(f"❌ 舊文字出現 {count} 次，請提供更多上下文使其唯一", file=sys.stderr)
        return 1

    new_content = content.replace(args.old, args.new, 1)
    _save_and_reload(new_content)
    print("✅ SOUL.md 已成功套用 diff 修改。")

def _save_and_reload(content: str):
    # 【本地優先】直接寫入檔案。這是最主要的操作。
    SOUL_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOUL_MD_PATH.write_text(content, encoding="utf-8")
    
    # 嘗試呼叫 API 重新載入（讓記憶體內的 Agent 即刻生效）
    trigger_reload(content)

def main():
    parser = argparse.ArgumentParser(
        description="SOUL.md 讀寫管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--command", choices=["read", "append", "replace", "diff"], required=True, help="執行動作 (read, append, replace, diff)")
    parser.add_argument("--text", help="附加或替換的文字內容 (append/replace 使用)")
    parser.add_argument("--old", help="diff 模式：要被替換的舊文字（需與 SOUL.md 完全一致）")
    parser.add_argument("--new", help="diff 模式：替換後的新文字")

    args = parser.parse_args()

    try:
        if args.command == "read":
            cmd_read(args)
        elif args.command == "append":
            if not args.text:
                print("❌ 錯誤: append 動作必須提供 --text 參數", file=sys.stderr)
                return 1
            cmd_append(args)
        elif args.command == "replace":
            if not args.text:
                print("❌ 錯誤: replace 動作必須提供 --text 參數", file=sys.stderr)
                return 1
            cmd_replace(args)
        elif args.command == "diff":
            if not args.old or args.new is None:
                print("❌ 錯誤: diff 動作必須提供 --old 與 --new 參數", file=sys.stderr)
                return 1
            cmd_diff(args)
        return 0
    except Exception as e:
        print(f"❌ 錯誤: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
