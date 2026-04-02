#!/usr/bin/env python3
"""
scripts/build_dxt.py

將 OpenSoul MCP Plugin 打包為 Claude Desktop Extension（.dxt）格式。

.dxt 本質是 ZIP 壓縮檔，包含：
  manifest.json     — 插件宣告
  soul_mcp/         — MCP server + tools + hooks
  soul/             — OpenSoul 核心（記憶/情感/人格/代理）

用法：
    python scripts/build_dxt.py
    python scripts/build_dxt.py --output dist/opensoul-v1.0.0.dxt
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"

INCLUDE_DIRS = ["soul_mcp", "soul"]
INCLUDE_FILES = [".env.example"]

EXCLUDE_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".pyd",
    ".DS_Store", "Thumbs.db",
    "tests", "test_",
    ".git", ".gitignore",
    "*.egg-info",
}


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        for pat in EXCLUDE_PATTERNS:
            if pat.startswith("*"):
                if part.endswith(pat[1:]):
                    return True
            elif part == pat or part.startswith(pat):
                return True
    return False


def build(output: Path) -> None:
    manifest = PROJECT_ROOT / "soul_mcp" / "manifest.json"
    if not manifest.exists():
        print(f"[ERR] manifest.json 不存在：{manifest}")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)

    file_count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        # manifest.json 置於根目錄
        zf.write(manifest, "manifest.json")
        file_count += 1

        # 遞迴加入各目錄
        for dir_name in INCLUDE_DIRS:
            src_dir = PROJECT_ROOT / dir_name
            if not src_dir.exists():
                print(f"[WARN] 目錄不存在，跳過：{src_dir}")
                continue
            for fpath in sorted(src_dir.rglob("*")):
                if not fpath.is_file():
                    continue
                rel = fpath.relative_to(PROJECT_ROOT)
                if should_exclude(rel):
                    continue
                zf.write(fpath, str(rel))
                file_count += 1

        # 單一附加檔案（.env.example）
        for fname in INCLUDE_FILES:
            fpath = PROJECT_ROOT / fname
            if fpath.exists():
                zf.write(fpath, fname)
                file_count += 1

    size_kb = output.stat().st_size / 1024
    print(f"[ OK ] 打包完成：{output}（{file_count} 個檔案，{size_kb:.1f} KB）")


def main() -> None:
    parser = argparse.ArgumentParser(description="打包 OpenSoul .dxt 插件")
    parser.add_argument("--output", default=str(DIST_DIR / "opensoul.dxt"),
                        help="輸出路徑（預設：dist/opensoul.dxt）")
    args = parser.parse_args()

    output = Path(args.output)
    print(f"[INFO] 開始打包 → {output}")
    build(output)


if __name__ == "__main__":
    main()
