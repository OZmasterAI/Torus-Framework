#!/bin/bash
# Run the Torus Evolution Sprint in Docker
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="torus-evolution"
CONTAINER_NAME="evolution-sprint"

echo "=== Torus Evolution Sprint ==="
echo ""

# ── Step 1: Build Docker image ──
echo "[1/3] Building Docker image..."
docker build \
    --build-arg HOST_UID=$(id -u) \
    --build-arg HOST_GID=$(id -g -r) \
    -t "$IMAGE_NAME" \
    "$SCRIPT_DIR"
echo ""

# ── Step 2: Stop existing container if running ──
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[2/3] Removing existing container..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
else
    echo "[2/3] No existing container to clean up"
fi
echo ""

# ── Step 3: Launch container ──
echo "[3/3] Launching sprint container..."
REPO_DIR="$HOME/.claude"
docker run -d \
    --name "$CONTAINER_NAME" \
    --network host \
    -v "$REPO_DIR:/mnt/repo:ro" \
    -v "/home/crab/.claude.json:/home/crab/.claude.json:ro" \
    -e "TERM=xterm-256color" \
    "$IMAGE_NAME"

echo ""
echo "=== Sprint Running ==="
echo ""
echo "  Watch live:    docker exec -it $CONTAINER_NAME tmux attach -t sprint"
echo "  View logs:     docker logs -f $CONTAINER_NAME"
echo "  Shell access:  docker exec -it $CONTAINER_NAME bash"
echo "  Stop sprint:   docker stop $CONTAINER_NAME"
echo ""
echo "The sprint is now running autonomously."
echo "All memory saves go to your shared memory server."
echo "Changes stay in the container — use 'docker cp' to extract."
