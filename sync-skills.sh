#!/bin/bash
# 同步 openclaw/skills 到 Docker 容器（無需重建整個鏡像）

set -e

SKILL_NAME=$1
CONTAINER_NAME="openclaw-openclaw-cli-1"

if [ -n "$SKILL_NAME" ]; then
    echo "📦 Syncing specific skill: $SKILL_NAME to $CONTAINER_NAME..."
    docker cp "./openclaw/skills/$SKILL_NAME/." "$CONTAINER_NAME:/app/skills/$SKILL_NAME/"
else
    echo "📦 Syncing all skills to $CONTAINER_NAME..."
    # 僅同步本地存在的技能目錄
    docker cp ./openclaw/skills/. "$CONTAINER_NAME:/app/skills/"
fi

echo "✅ Skills synced successfully!"
echo ""
echo "Usage:"
echo "  ./sync-skills.sh           # Sync all"
echo "  ./sync-skills.sh <skill>   # Sync specific skill"
