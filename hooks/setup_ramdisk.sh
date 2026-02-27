#!/usr/bin/env bash
# One-time setup for hybrid tmpfs ramdisk
# Creates tmpfs directories, disk backup, migrates existing files, installs systemd service.
#
# Usage: bash ~/.claude/hooks/setup_ramdisk.sh

set -euo pipefail

UID_NUM=$(id -u)
RAMDISK_DIR="/run/user/${UID_NUM}/claude-hooks"
HOOKS_DIR="$HOME/.claude/hooks"
BACKUP_DIR="${HOOKS_DIR}/.disk_backup"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "=== Claude Hooks Ramdisk Setup ==="
echo ""

# 1. Verify /run/user/<uid> exists (systemd tmpfs)
if [ ! -d "/run/user/${UID_NUM}" ]; then
    echo "ERROR: /run/user/${UID_NUM} does not exist."
    echo "This system may not use systemd or the user session is not active."
    exit 1
fi

# 2. Create tmpfs directories
echo "[1/5] Creating tmpfs directories..."
mkdir -p "${RAMDISK_DIR}/audit"
mkdir -p "${RAMDISK_DIR}/state"
echo "  Created: ${RAMDISK_DIR}/{audit,state}"

# 3. Create disk backup directory
echo "[2/5] Creating disk backup directory..."
mkdir -p "${BACKUP_DIR}/audit"
echo "  Created: ${BACKUP_DIR}/audit"

# 4. Migrate existing audit files
echo "[3/5] Migrating existing files..."
MIGRATED=0

# Migrate audit files to both tmpfs and backup
if [ -d "${HOOKS_DIR}/audit" ]; then
    for f in "${HOOKS_DIR}/audit/"*.jsonl; do
        [ -f "$f" ] || continue
        fname=$(basename "$f")
        # Copy to tmpfs (active)
        cp "$f" "${RAMDISK_DIR}/audit/${fname}" 2>/dev/null && MIGRATED=$((MIGRATED + 1))
        # Copy to backup (persistent)
        cp "$f" "${BACKUP_DIR}/audit/${fname}" 2>/dev/null
    done
fi

echo "  Migrated ${MIGRATED} audit file(s)"

# 5. Install systemd shutdown hook
echo "[4/5] Installing systemd shutdown hook..."
mkdir -p "${SYSTEMD_DIR}"

cat > "${SYSTEMD_DIR}/claude-hooks-sync.service" << 'UNIT'
[Unit]
Description=Sync Claude hooks tmpfs to disk backup
DefaultDependencies=no
Before=shutdown.target reboot.target halt.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %h/.claude/hooks/shared/ramdisk.py sync
TimeoutStartSec=10

[Install]
WantedBy=shutdown.target reboot.target halt.target
UNIT

# Enable the service
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable claude-hooks-sync.service 2>/dev/null || true
echo "  Installed and enabled claude-hooks-sync.service"

# 6. Verification
echo "[5/5] Verifying setup..."
echo ""
PASS=true

if [ -d "${RAMDISK_DIR}/audit" ] && [ -d "${RAMDISK_DIR}/state" ]; then
    echo "  [OK] tmpfs dirs exist"
else
    echo "  [FAIL] tmpfs dirs missing"
    PASS=false
fi

if [ -d "${BACKUP_DIR}/audit" ]; then
    echo "  [OK] backup dir exists"
else
    echo "  [FAIL] backup dir missing"
    PASS=false
fi

# Write test
if echo "test" > "${RAMDISK_DIR}/.write_test" 2>/dev/null && rm "${RAMDISK_DIR}/.write_test"; then
    echo "  [OK] tmpfs writable"
else
    echo "  [FAIL] tmpfs not writable"
    PASS=false
fi

if systemctl --user is-enabled claude-hooks-sync.service &>/dev/null; then
    echo "  [OK] systemd service enabled"
else
    echo "  [WARN] systemd service not enabled (optional)"
fi

echo ""
if $PASS; then
    echo "=== Setup complete! Ramdisk ready at ${RAMDISK_DIR} ==="
else
    echo "=== Setup completed with warnings ==="
fi
