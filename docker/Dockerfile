FROM node:25-bookworm-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    tmux git curl jq rsync \
    && rm -rf /var/lib/apt/lists/*

# Create crab user matching host uid (node image already has uid 1000 as 'node')
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN userdel -r node 2>/dev/null || true && \
    groupadd -g ${HOST_GID} crab 2>/dev/null || true && \
    useradd -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/bash crab

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code@latest

# Bare minimum ~/.claude config — NO hooks, NO plugins, NO MCP
RUN mkdir -p /home/crab/.claude && \
    echo '{}' > /home/crab/.claude/settings.json && \
    echo '{"mcpServers":{}}' > /home/crab/.claude/mcp.json && \
    chown -R crab:crab /home/crab/.claude

USER crab
WORKDIR /home/crab

# Entrypoint
COPY --chown=crab:crab entrypoint.sh /home/crab/entrypoint.sh
RUN chmod +x /home/crab/entrypoint.sh

ENTRYPOINT ["/home/crab/entrypoint.sh"]
