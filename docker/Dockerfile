FROM node:25-bookworm-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    tmux git curl jq \
    && rm -rf /var/lib/apt/lists/*

# Create user matching host uid
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -g ${HOST_GID} crab 2>/dev/null || true && \
    useradd -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/bash crab 2>/dev/null || true

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code@latest

# Python deps for hooks/gates/MCP servers (no torch — memory runs on host)
RUN python3 -m pip install --break-system-packages --no-cache-dir \
    "mcp>=1.0,<2.0" \
    "fastmcp>=2.0" \
    "lancedb>=0.29,<1.0" \
    "pyarrow>=14.0" \
    "httpx>=0.28" \
    "pydantic>=2.0"

USER crab
WORKDIR /home/crab

# Entrypoint
COPY --chown=crab:crab entrypoint.sh /home/crab/entrypoint.sh
RUN chmod +x /home/crab/entrypoint.sh

ENTRYPOINT ["/home/crab/entrypoint.sh"]
