#!/bin/bash
# Run the Torus Evolution Sprint in Docker
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKTREE="/home/crab/agents/evolution-sprint"
IMAGE_NAME="torus-evolution"
CONTAINER_NAME="evolution-sprint"

echo "=== Torus Evolution Sprint ==="
echo ""

# ── Step 1: Prepare worktree ──
echo "[1/4] Preparing worktree..."
bash "$SCRIPT_DIR/prepare-worktree.sh"
echo ""

# ── Step 2: Build Docker image ──
echo "[2/4] Building Docker image..."
docker build \
    --build-arg HOST_UID=$(id -u) \
    --build-arg HOST_GID=$(id -g -r) \
    -t "$IMAGE_NAME" \
    "$SCRIPT_DIR"
echo ""

# ── Step 3: Stop existing container if running ──
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[3/4] Removing existing container..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
else
    echo "[3/4] No existing container to clean up"
fi
echo ""

# ── Step 4: Launch container ──
echo "[4/4] Launching sprint container..."
# Require API key (OAuth is interactive-only, won't work headless)
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set. OAuth won't work headless in Docker."
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi

docker run -d \
    --name "$CONTAINER_NAME" \
    --network host \
    -v "$WORKTREE:/home/crab/.claude:rw" \
    -v "/home/crab/.claude/docker/sprint-prompt.md:/home/crab/.claude/docker/sprint-prompt.md:ro" \
    -e "TERM=xterm-256color" \
    -e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" \
    "$IMAGE_NAME"

echo ""
echo "=== Sprint Running ==="
echo ""
echo "  Watch live:    docker exec -it $CONTAINER_NAME tmux attach -t sprint"
echo "  View logs:     docker logs -f $CONTAINER_NAME"
echo "  Shell access:  docker exec -it $CONTAINER_NAME bash"
echo "  Stop sprint:   docker stop $CONTAINER_NAME"
echo "  View changes:  cd $WORKTREE && git diff"
echo ""
echo "The sprint is now running autonomously."
echo "All memory saves go to your shared memory server."
echo "Changes stay isolated in: $WORKTREE"
