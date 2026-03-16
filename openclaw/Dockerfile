# 使用官方支援 ARM64 的鏡像作為基底
FROM ghcr.io/openclaw/openclaw:latest

# 定義建置參數，對齊 docker-setup.sh 的需求
ARG OPENCLAW_DOCKER_APT_PACKAGES=""
ARG OPENCLAW_INSTALL_DOCKER_CLI=""

USER root

# 安裝 Python 3 與額外的 apt 套件
# 這是為了確保容器內部也能解析與執行 Python 技能
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates curl gnupg lsb-release \
    $OPENCLAW_DOCKER_APT_PACKAGES && \
    pip3 install --no-cache-dir --break-system-packages seleniumbase markdownify && \
    rm -rf /var/lib/apt/lists/*

# 安裝 Docker CLI（用於 Sandbox 功能）
RUN if [ "$OPENCLAW_INSTALL_DOCKER_CLI" = "1" ]; then \
      install -m 0755 -d /etc/apt/keyrings && \
      curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
      chmod a+r /etc/apt/keyrings/docker.gpg && \
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null && \
      apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
      rm -rf /var/lib/apt/lists/*; \
    fi

# 建立配置與技能目錄，確保 node 使用者擁有存取權
RUN mkdir -p /home/node/.openclaw/skills && \
    mkdir -p /home/node/.openclaw/workspace && \
    chown -R node:node /home/node/.openclaw

# 複製本地 skills 目錄（必須在技能依賴安裝之前）
COPY --chown=node:node skills/ /home/node/.openclaw/skills/

# 🆕 通用技能依賴自動安裝：掃描所有 SKILL.md 並安裝依賴
# summarize 是 Node.js 工具，直接用 npm 全域安裝
RUN if [ -d /home/node/.openclaw/skills/summarize ]; then \
      echo "📦 安裝 summarize (npm)..."; \
      npm install -g @steipete/summarize; \
    fi

# 切換回 node 使用者
USER node
