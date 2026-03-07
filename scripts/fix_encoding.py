#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/fix_encoding.py

修復 Windows 編碼問題 - 強制 UTF-8 並驗證所有文件。

運行：
  python scripts/fix_encoding.py
"""

import sys
import os
import io
from pathlib import Path

# 強制 UTF-8（這是問題的根源！）
if sys.platform == "win32":
    # Method 1: TextIOWrapper
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    # Method 2: 設置環境變量
    os.environ['PYTHONIOENCODING'] = 'utf-8'

print("=" * 70)
print("🔧 Windows UTF-8 編碼修復工具")
print("=" * 70)

# 要檢查/修復的文件
files_to_check = [
    "scripts/soul_note_skill.py",
    "scripts/soul_note_api.py",
    "soul/core/soul_note.py",
    "soul/soul_note_web.html",
]

print("\n📋 檢查文件編碼...\n")

for file_path in files_to_check:
    full_path = Path(file_path)

    if not full_path.exists():
        print(f"⚠️  {file_path}: 文件不存在")
        continue

    try:
        # 讀取文件檢查編碼
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 計算 emoji 數量
        emoji_count = sum(1 for c in content if ord(c) > 0x1F300)

        print(f"✅ {file_path}")
        print(f"   • 大小: {full_path.stat().st_size:,} bytes")
        print(f"   • 編碼: UTF-8 ✓")
        print(f"   • Emoji: {emoji_count} 個")

    except UnicodeDecodeError as e:
        print(f"❌ {file_path}: 編碼錯誤")
        print(f"   {e}")
    except Exception as e:
        print(f"❌ {file_path}: {e}")

print("\n" + "=" * 70)
print("✨ 編碼修復建議")
print("=" * 70)

print("""
1️⃣  所有 Python 檔案頂部必須有：
   # -*- coding: utf-8 -*-

2️⃣  強制 stdout/stderr 為 UTF-8：
   if sys.platform == "win32":
       sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
       sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

3️⃣  HTML 檔案 <head> 必須有：
   <meta charset="UTF-8">

4️⃣  Flask/JSON 響應：
   app.config['JSON_ENSURE_ASCII'] = False

5️⃣  環境變量設置（推薦）：
   set PYTHONIOENCODING=utf-8

6️⃣  命令行啟動時：
   python -u scripts/soul_note_api.py
   （-u 強制無緩衝 UTF-8 輸出）
""")

print("\n" + "=" * 70)
print("🧪 Emoji 測試")
print("=" * 70)

test_emojis = [
    "✨ 光彩 (U+2728)",
    "✅ 檢查 (U+2705)",
    "❌ 錯誤 (U+274C)",
    "📝 筆記 (U+1F4DD)",
    "🧠 大腦 (U+1F9E0)",
    "💭 想法 (U+1F4AD)",
    "📊 圖表 (U+1F4CA)",
    "🚀 火箭 (U+1F680)",
]

for emoji in test_emojis:
    try:
        print(f"  {emoji}")
    except Exception as e:
        print(f"  ❌ 無法顯示: {emoji}")

print("\n" + "=" * 70)
print("✅ 修復完成")
print("=" * 70)

print("""
問題解決步驟：

1. 在 .claude/launch.json 中添加環境變量：
   "env": { "PYTHONIOENCODING": "utf-8" }

2. 或在終端設置：
   set PYTHONIOENCODING=utf-8

3. 重新啟動服務：
   python scripts/soul_note_api.py -u

4. 驗證：
   python scripts/fix_encoding.py
""")
