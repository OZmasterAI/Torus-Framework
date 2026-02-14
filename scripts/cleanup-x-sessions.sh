#!/bin/bash
# cleanup-x-sessions.sh — Remove stale X session lock files and sockets
#
# Iterates /tmp/.X*-lock files, checks if the owning PID is alive.
# Dead PIDs → remove lock file + socket. Alive but old → log warning.
#
# Environment variables:
#   X_CLEANUP_DRY_RUN=true       — Log what would happen without removing anything
#   X_CLEANUP_MAX_AGE_HOURS=48   — Warn threshold for old-but-alive sessions
#
# Usage: cleanup-x-sessions.sh
# Cron:  0 */6 * * * /home/crab/.claude/scripts/cleanup-x-sessions.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
DRY_RUN="${X_CLEANUP_DRY_RUN:-false}"
MAX_AGE_HOURS="${X_CLEANUP_MAX_AGE_HOURS:-48}"
MAX_AGE_SECONDS=$((MAX_AGE_HOURS * 3600))
LOG_DIR="$HOME/.claude/logs"

# ── Logging ────────────────────────────────────────────────────────
log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
}

log_info()  { log "INFO"  "$@"; }
log_warn()  { log "WARN"  "$@"; }
log_error() { log "ERROR" "$@"; }

# ── Ensure log directory ───────────────────────────────────────────
mkdir -p "$LOG_DIR"

# ── Counters ───────────────────────────────────────────────────────
checked=0
removed=0
warned=0
errors=0

log_info "=== X session cleanup started (dry_run=$DRY_RUN, max_age=${MAX_AGE_HOURS}h) ==="

# ── Find lock files ───────────────────────────────────────────────
shopt -s nullglob
lock_files=(/tmp/.X*-lock)
shopt -u nullglob

if [[ ${#lock_files[@]} -eq 0 ]]; then
    log_info "No X lock files found in /tmp — nothing to do"
    log_info "=== Cleanup complete: checked=0 removed=0 warned=0 errors=0 ==="
    exit 0
fi

for lock_file in "${lock_files[@]}"; do
    checked=$((checked + 1))

    # Validate lock file name pattern (must be .X<number>-lock)
    basename_file="$(basename "$lock_file")"
    if [[ ! "$basename_file" =~ ^\.X([0-9]+)-lock$ ]]; then
        log_warn "Skipping unexpected file: $lock_file"
        continue
    fi
    display_num="${BASH_REMATCH[1]}"

    # Read PID from lock file
    if [[ ! -r "$lock_file" ]]; then
        log_error "Cannot read lock file: $lock_file (permission denied)"
        errors=$((errors + 1))
        continue
    fi

    pid="$(tr -d '[:space:]' < "$lock_file")"

    if [[ -z "$pid" ]]; then
        log_warn "Empty lock file: $lock_file — treating as stale"
        pid="0"
    fi

    if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
        log_error "Invalid PID '$pid' in $lock_file — skipping"
        errors=$((errors + 1))
        continue
    fi

    # Determine corresponding socket path
    socket_path="/tmp/.X11-unix/X${display_num}"

    # Check if PID is alive
    if kill -0 "$pid" 2>/dev/null; then
        # PID is alive — check age
        if [[ -f "/proc/$pid/stat" ]]; then
            # Get process start time from /proc
            proc_start=$(stat -c %Y "/proc/$pid" 2>/dev/null || echo "0")
            now=$(date +%s)
            age_seconds=$((now - proc_start))

            if [[ $age_seconds -gt $MAX_AGE_SECONDS ]]; then
                age_hours=$((age_seconds / 3600))
                log_warn "STALE-ALIVE: $lock_file (PID $pid, age ${age_hours}h) — exceeds ${MAX_AGE_HOURS}h threshold, NOT removing (process alive)"
                warned=$((warned + 1))
            else
                log_info "ALIVE: $lock_file (PID $pid) — session active, skipping"
            fi
        else
            log_info "ALIVE: $lock_file (PID $pid) — session active, skipping (no /proc info)"
        fi
    else
        # PID is dead — clean up
        log_info "DEAD: $lock_file (PID $pid) — process not running"

        if [[ "$DRY_RUN" == "true" ]]; then
            log_info "DRY-RUN: Would remove $lock_file"
            if [[ -e "$socket_path" ]]; then
                log_info "DRY-RUN: Would remove $socket_path"
            fi
            removed=$((removed + 1))
        else
            # Remove lock file
            if rm -f "$lock_file" 2>/dev/null; then
                log_info "REMOVED: $lock_file"
            else
                log_error "FAILED to remove $lock_file"
                errors=$((errors + 1))
            fi

            # Remove socket if it exists
            if [[ -e "$socket_path" ]]; then
                if rm -f "$socket_path" 2>/dev/null; then
                    log_info "REMOVED: $socket_path"
                else
                    log_error "FAILED to remove $socket_path"
                    errors=$((errors + 1))
                fi
            else
                log_info "No socket at $socket_path (already gone)"
            fi

            removed=$((removed + 1))
        fi
    fi
done

log_info "=== Cleanup complete: checked=$checked removed=$removed warned=$warned errors=$errors ==="

# Exit with error code if there were failures
if [[ $errors -gt 0 ]]; then
    exit 1
fi
exit 0
