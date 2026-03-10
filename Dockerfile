FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and README first for better caching
COPY pyproject.toml README.md ./

# Copy the actual source code
COPY soul/ soul/
COPY openclaw/ openclaw/
# 複製 skills（包含 50+ 個 Python skills）
COPY openclaw/skills/ openclaw/skills/

# Copy workspace initial files (SOUL.md, MEMORY.md etc.)
# 若 docker-compose volume 有正確掛載則會被覆蓋；否則使用此預設值
COPY workspace/ workspace/

# Install the package and its dependencies
RUN pip install --no-cache-dir .

# Expose the API port
EXPOSE 8001

# Run the API
CMD ["uvicorn", "soul.interface.api:app", "--host", "0.0.0.0", "--port", "8001"]
