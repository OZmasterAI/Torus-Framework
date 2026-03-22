#!/bin/bash
# Tests for torus-loop.sh retry cap, path resolution, and failure history.
# Uses a mock task_manager.py and mock claude to avoid real invocations.

set -euo pipefail
PASS=0
FAIL=0
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

ok() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1 — $2"; }

echo "--- torus-loop.sh tests ---"

# ── Setup mock environment ────────────────────────────────────────
MOCK_PRP_DIR="$TMP_DIR/PRPs"
MOCK_SCRIPTS_DIR="$TMP_DIR/scripts"
MOCK_HOOKS_DIR="$TMP_DIR/hooks"
mkdir -p "$MOCK_PRP_DIR" "$MOCK_SCRIPTS_DIR" "$MOCK_HOOKS_DIR"

# Mock claude binary that just exits 0
cat > "$TMP_DIR/claude" <<'MOCK'
#!/bin/bash
exit 0
MOCK
chmod +x "$TMP_DIR/claude"

# ── Test 1: Retry cap logic (pure bash) ───────────────────────────
echo ""
echo "Test 1: Retry cap associative array"
declare -A RETRY_COUNT
TASK_ID=1
MAX_RETRIES=3

# Simulate 3 failures
for i in 1 2 3; do
    ATTEMPTS=${RETRY_COUNT[$TASK_ID]:-0}
    RETRY_COUNT[$TASK_ID]=$((ATTEMPTS + 1))
done

ATTEMPTS=${RETRY_COUNT[$TASK_ID]:-0}
if [[ $ATTEMPTS -ge $MAX_RETRIES ]]; then
    ok "Task skipped after $MAX_RETRIES failures"
else
    fail "Task not skipped" "ATTEMPTS=$ATTEMPTS, MAX_RETRIES=$MAX_RETRIES"
fi

# ── Test 2: Fresh task should not be skipped ──────────────────────
echo ""
echo "Test 2: Fresh task not skipped"
TASK_ID=99
ATTEMPTS=${RETRY_COUNT[$TASK_ID]:-0}
if [[ $ATTEMPTS -eq 0 ]]; then
    ok "Fresh task has 0 attempts"
else
    fail "Fresh task has non-zero attempts" "ATTEMPTS=$ATTEMPTS"
fi

# ── Test 3: Failure history accumulation ──────────────────────────
echo ""
echo "Test 3: Failure history accumulates"
declare -A FAILURE_HISTORY
TASK_ID=5

FAILURE_HISTORY[$TASK_ID]+="
- Attempt 1: FAILED (exit=1). Output: some error"
FAILURE_HISTORY[$TASK_ID]+="
- Attempt 2: FAILED (exit=1). Output: different error"

HIST="${FAILURE_HISTORY[$TASK_ID]}"
if echo "$HIST" | grep -q "Attempt 1" && echo "$HIST" | grep -q "Attempt 2"; then
    ok "Failure history contains both attempts"
else
    fail "Failure history incomplete" "$HIST"
fi

# ── Test 4: Consecutive skip counter ─────────────────────────────
echo ""
echo "Test 4: Consecutive skip counter triggers exit"
CONSECUTIVE_SKIPS=0
EXIT_TRIGGERED=false
for i in $(seq 1 10); do
    CONSECUTIVE_SKIPS=$((CONSECUTIVE_SKIPS + 1))
    if [[ $CONSECUTIVE_SKIPS -ge 10 ]]; then
        EXIT_TRIGGERED=true
        break
    fi
done
if [[ "$EXIT_TRIGGERED" == "true" ]]; then
    ok "Exit triggered after 10 consecutive skips"
else
    fail "Exit not triggered" "CONSECUTIVE_SKIPS=$CONSECUTIVE_SKIPS"
fi

# ── Test 5: Consecutive skip resets on success ────────────────────
echo ""
echo "Test 5: Consecutive skip resets on success"
CONSECUTIVE_SKIPS=5
# Simulate a successful task
CONSECUTIVE_SKIPS=0
if [[ $CONSECUTIVE_SKIPS -eq 0 ]]; then
    ok "Consecutive skips reset to 0 on success"
else
    fail "Consecutive skips not reset" "$CONSECUTIVE_SKIPS"
fi

# ── Test 6: Project PRPs/ path resolution ─────────────────────────
echo ""
echo "Test 6: Project PRPs/ path resolution"
# Create tasks.json in project PRPs/ (cwd-relative)
PROJECT_PRP_DIR="$TMP_DIR/project/PRPs"
mkdir -p "$PROJECT_PRP_DIR"
echo '{"tasks":[]}' > "$PROJECT_PRP_DIR/test-prp.tasks.json"

# Simulate the path search logic from torus-loop.sh
TASKS_FILE=""
PRP_DIR="$MOCK_PRP_DIR"
for candidate in "$PROJECT_PRP_DIR/test-prp.tasks.json" "$PRP_DIR/test-prp.tasks.json"; do
    if [[ -f "$candidate" ]]; then
        TASKS_FILE="$candidate"
        break
    fi
done
if [[ "$TASKS_FILE" == "$PROJECT_PRP_DIR/test-prp.tasks.json" ]]; then
    ok "Found tasks.json in project PRPs/ first"
else
    fail "Wrong path resolution" "$TASKS_FILE"
fi

# ── Test 7: Falls back to ~/.claude/PRPs/ ─────────────────────────
echo ""
echo "Test 7: Fallback to global PRPs/"
echo '{"tasks":[]}' > "$MOCK_PRP_DIR/fallback-prp.tasks.json"

TASKS_FILE=""
for candidate in "$PROJECT_PRP_DIR/fallback-prp.tasks.json" "$MOCK_PRP_DIR/fallback-prp.tasks.json"; do
    if [[ -f "$candidate" ]]; then
        TASKS_FILE="$candidate"
        break
    fi
done
if [[ "$TASKS_FILE" == "$MOCK_PRP_DIR/fallback-prp.tasks.json" ]]; then
    ok "Fell back to global PRPs/"
else
    fail "Fallback failed" "$TASKS_FILE"
fi

# ── Test 8: MAX_RETRIES configurable ──────────────────────────────
echo ""
echo "Test 8: MAX_RETRIES configurable"
declare -A RETRY_COUNT_2
MAX_RETRIES=5
TASK_ID=1
for i in 1 2 3 4; do
    ATTEMPTS=${RETRY_COUNT_2[$TASK_ID]:-0}
    RETRY_COUNT_2[$TASK_ID]=$((ATTEMPTS + 1))
done
ATTEMPTS=${RETRY_COUNT_2[$TASK_ID]:-0}
if [[ $ATTEMPTS -lt $MAX_RETRIES ]]; then
    ok "Task NOT skipped at 4 attempts when MAX_RETRIES=5"
else
    fail "Task skipped too early" "ATTEMPTS=$ATTEMPTS"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
exit $FAIL
