#!/bin/bash
# 通用技能依賴安裝腳本
# 自動掃描所有 skills，根據 SKILL.md 的 metadata 安裝依賴

set -e

SKILLS_DIR="${1:-.}"

echo "📦 正在安裝技能依賴..."

# 掃描所有 skills 目錄
for skill_dir in "$SKILLS_DIR"/*; do
    [ -d "$skill_dir" ] || continue
    skill_name=$(basename "$skill_dir")
    skill_md="$skill_dir/SKILL.md"

    # 跳過沒有 SKILL.md 的技能
    [ -f "$skill_md" ] || continue

    echo ""
    echo "🔍 檢查技能: $skill_name"

    # 使用 Python 解析 SKILL.md 的 YAML frontmatter
    python3 << EOF
import sys
import re

skill_name = "$skill_name"
skill_md = "$skill_md"

try:
    with open(skill_md, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取 YAML frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        sys.exit(0)

    yaml_str = match.group(1)

    # 簡單的 YAML 解析（只提取所需部分）
    if 'requires:' in yaml_str:
        # 提取 requires 中的 bins 列表
        bins_match = re.search(r'"bins":\s*\[(.*?)\]', yaml_str)
        if bins_match:
            bins_str = bins_match.group(1)
            bins = [b.strip().strip('"') for b in bins_str.split(',')]
            print(f"  需要: {', '.join(bins)}")

            # 檢查是否已安裝
            for bin_name in bins:
                if __import__('shutil').which(bin_name):
                    print(f"    ✅ {bin_name} 已安裝")
                else:
                    print(f"    ⚠️  {bin_name} 缺失")

except Exception as e:
    print(f"  ℹ️  無法解析 metadata: {e}", file=sys.stderr)
    sys.exit(0)
EOF

done

echo ""
echo "✅ 依賴檢查完成"
