#!/usr/bin/env python3
"""Self-Healing Claude Framework — Status Line

Generates a 2-line status display for the Claude Code UI. Reads session data
from stdin (JSON with costs, context usage, etc.) and outputs two formatted lines.

Line 1: [Model] 📁 project | 🌿 branch | 🛡️ G:14 S:18 | 🧠 M:359 | ⚡ TC:42
Line 2: ██████░░░░ 62% | 19.7k tok (1.2k>0.8k) | ⏱️ 15m | +120/-34 | V:3/5 | $0.42

Usage: Configured in settings.json as "statusLine" command.

Claude Code sends nested JSON via stdin:
  cost.total_cost_usd, cost.total_duration_ms, cost.total_lines_added,
  cost.total_lines_removed, context_window.used_percentage,
  context_window.total_input_tokens, context_window.total_output_tokens,
  context_window.current_usage.input_tokens, context_window.current_usage.output_tokens,
  model.display_name
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from shared.memory_socket import is_worker_available, count as socket_count, WorkerUnavailable

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")

# State files may live on tmpfs ramdisk for performance
try:
    from shared.ramdisk import get_state_dir, is_ramdisk_available, RAMDISK_DIR, TMPFS_AUDIT_DIR, BACKUP_AUDIT_DIR
    STATE_FILE_DIR = get_state_dir()
    _HAS_RAMDISK = True
except ImportError:
    STATE_FILE_DIR = HOOKS_DIR
    _HAS_RAMDISK = False
GATES_DIR = os.path.join(HOOKS_DIR, "gates")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
MODES_DIR = os.path.join(CLAUDE_DIR, "modes")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
STATS_CACHE = os.path.join(CLAUDE_DIR, "stats-cache.json")
SETTINGS_FILE = os.path.join(CLAUDE_DIR, "settings.json")

# Cache memory count for 60 seconds to avoid cold-starting LanceDB on every render
CACHE_TTL = 60

# Expected component counts (update when adding new gates/skills/hooks)
EXPECTED_GATES = 17
EXPECTED_SKILLS = 33
EXPECTED_HOOK_EVENTS = 13

# Health bar characters (legacy — kept for reference)
BAR_WIDTH = 10

# ANSI color codes for health bar
COLOR_CYAN = "\033[96m"     # 100%        — perfect health
COLOR_GREEN = "\033[92m"    # 90-99%      — healthy
COLOR_ORANGE = "\033[38;5;208m"  # 75-89% — warning
COLOR_YELLOW = "\033[93m"   # 50-74%      — degraded
COLOR_RED = "\033[91m"      # <50%        — critical
COLOR_DARK_ORANGE = "\033[38;5;166m"  # dark orange — Opus model bracket
COLOR_RESET = "\033[0m"


DORMANT_GATES = {"gate_08_temporal.py"}

def count_gates():
    """Count active gate_*.py files in the gates directory (excludes dormant/merged)."""
    if not os.path.isdir(GATES_DIR):
        return 0
    return len([f for f in os.listdir(GATES_DIR)
                if f.startswith("gate_") and f.endswith(".py") and f not in DORMANT_GATES])


def get_memory_count():
    """Get curated memory count, cached to avoid frequent UDS calls."""
    # Try cache first
    try:
        if os.path.exists(STATS_CACHE):
            with open(STATS_CACHE) as f:
                cache = json.load(f)
            if time.time() - cache.get("ts", 0) < CACHE_TTL:
                return cache.get("mem_count", "?")
    except (json.JSONDecodeError, OSError):
        pass

    # Cache miss — query via UDS socket (fast, no subprocess needed)
    try:
        count = socket_count("knowledge")
        # Write cache
        try:
            with open(STATS_CACHE, "w") as f:
                json.dump({"ts": time.time(), "mem_count": count}, f)
        except OSError:
            pass
        return count
    except (WorkerUnavailable, RuntimeError, OSError):
        pass

    # UDS unavailable — return stale cache or "?"
    try:
        if os.path.exists(STATS_CACHE):
            with open(STATS_CACHE) as f:
                cache = json.load(f)
            return cache.get("mem_count", "?")
    except (json.JSONDecodeError, OSError):
        pass
    return "?"


def fmt_tokens(n):
    """Format token count compactly: 834 → '834', 19700 → '19.7k', 1500000 → '1.5M'."""
    if not isinstance(n, (int, float)) or n <= 0:
        return "0"
    if n < 1000:
        return str(int(n))
    if n < 1_000_000:
        k = n / 1000
        return f"{k:.1f}k" if k < 100 else f"{int(k)}k"
    m = n / 1_000_000
    return f"{m:.1f}M"


def get_session_number():
    """Read current session number from LIVE_STATE.json.

    session_count is set to N by session_end.py at the end of session N-1,
    so it already represents the current session number.
    """
    try:
        with open(LIVE_STATE_FILE) as f:
            state = json.load(f)
        count = state.get("session_count", 0)
        return count if isinstance(count, int) else "?"
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "?"


def get_project_name():
    """Read project name from LIVE_STATE.json."""
    try:
        with open(LIVE_STATE_FILE) as f:
            state = json.load(f)
        name = state.get("project") or "claude"
        # Use short alias for known long names
        aliases = {
            "self-healing-framework": "shf",
        }
        return (aliases.get(name, name) or "claude")[:12]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "claude"


def count_skills():
    """Count SKILL.md directories in the skills directory."""
    if not os.path.isdir(SKILLS_DIR):
        return 0
    count = 0
    for entry in os.listdir(SKILLS_DIR):
        skill_file = os.path.join(SKILLS_DIR, entry, "SKILL.md")
        if os.path.isfile(skill_file):
            count += 1
    return count


def count_hook_events():
    """Count registered hook events in settings.json."""
    try:
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)
        return len(settings.get("hooks", {}))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0


def _load_session_state():
    """Load the most recent session state file once. All state readers use this."""
    import glob as globmod
    pattern = os.path.join(STATE_FILE_DIR, "state_*.json")
    files = globmod.glob(pattern)
    if not files:
        return {}
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    try:
        with open(files[0]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_error_pressure(state):
    """Read error_pattern_counts from session state. Returns total error count (0 = healthy)."""
    counts = state.get("error_pattern_counts", {})
    return sum(counts.values()) if counts else 0


def get_error_velocity(state):
    """Calculate error velocity from session state.

    Returns (recent_count, total_count) tuple where:
      - recent_count: errors in last 300 seconds (5 minutes)
      - total_count: all errors in error_windows
    """
    error_windows = state.get("error_windows", [])
    if not error_windows:
        return (0, 0)

    now = time.time()
    recent_threshold = 300  # 5 minutes
    recent_count = 0
    total_count = 0

    for entry in error_windows:
        if isinstance(entry, dict):
            last_seen = entry.get("last_seen", 0)
            count = entry.get("count", 1)
            total_count += count
            if now - last_seen < recent_threshold:
                recent_count += count

    return (recent_count, total_count)


def get_most_used_tool(state):
    """Read tool_stats from session state, return (name, count) or None."""
    tool_stats = state.get("tool_stats", {})
    if not tool_stats:
        return None
    try:
        top = max(tool_stats.items(), key=lambda x: x[1].get("count", 0))
        return (top[0], top[1]["count"])
    except (ValueError, KeyError):
        return None


def get_total_tool_calls(state):
    """Read total_tool_calls from session state."""
    return state.get("total_tool_calls", 0)


def get_session_age(state):
    """Format session age from state's session_start timestamp."""
    now = time.time()
    session_start = state.get("session_start", now)
    elapsed = int(now - session_start)
    if elapsed < 60:
        return "<1m"
    total_minutes = elapsed // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours == 0:
        return f"{minutes}m"
    if minutes == 0:
        return f"{hours}h"
    return f"{hours}h{minutes}m"


def get_pending_count(state):
    """Return count of files awaiting verification from session state."""
    return len(state.get("pending_verification", []))


def get_subagent_status(state):
    """Read active subagents from session state and sum their live token usage.

    For each active subagent, reads its transcript JSONL and sums
    usage.input_tokens + usage.output_tokens from all assistant messages.

    Returns (active_list, total_completed_tokens) where active_list is
    [(agent_type, live_tokens), ...] and total_completed_tokens is the
    cumulative tokens from all finished subagents.
    """
    completed_tokens = state.get("subagent_total_tokens", 0)
    active = state.get("active_subagents", [])
    if not active:
        return ([], completed_tokens)

    # Read live token counts from each active subagent's transcript
    active_list = []
    for sa in active:
        agent_type = sa.get("agent_type", "?")
        transcript = sa.get("transcript_path", "")
        tokens = 0
        if transcript and os.path.isfile(transcript):
            try:
                with open(transcript) as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                            usage = entry.get("message", {}).get("usage", {})
                            tokens += usage.get("input_tokens", 0)
                            tokens += usage.get("output_tokens", 0)
                        except (json.JSONDecodeError, AttributeError):
                            continue
            except OSError:
                pass
        active_list.append((agent_type, tokens))
    return (active_list, completed_tokens)


def get_active_mode():
    """Read active behavioral mode from ~/.claude/modes/.active.
    Returns short mode name (e.g. 'code') or None if no mode active."""
    active_file = os.path.join(MODES_DIR, ".active")
    try:
        with open(active_file) as f:
            name = f.read().strip()
        if name:
            # Use short abbreviations for known modes
            abbrevs = {"coding": "code", "review": "rev", "debug": "dbg", "docs": "docs"}
            return abbrevs.get(name, name[:6])
        return None
    except (FileNotFoundError, OSError):
        return None


DOMAINS_DIR = os.path.join(CLAUDE_DIR, "domains")


def _get_active_domain():
    """Read active domain from ~/.claude/domains/.active.
    Returns short domain name (max 8 chars) or None."""
    active_file = os.path.join(DOMAINS_DIR, ".active")
    try:
        with open(active_file) as f:
            name = f.read().strip()
        if name:
            return name[:8]
        return None
    except (FileNotFoundError, OSError):
        return None


def get_plan_mode_warns(state):
    """Return Gate 6 save-to-memory escalation warn count from session state.

    Gate 12 was merged into Gate 6 in refactor1 — now uses gate6_warn_count.
    """
    return state.get("gate6_warn_count", 0)


def get_verification_ratio(state):
    """Return (verified, total) from session state for V:x/y display."""
    verified = len(state.get("verified_fixes", []))
    pending = len(state.get("pending_verification", []))
    return (verified, verified + pending)


def get_ramdisk_health():
    """Return ramdisk health info: (used_bytes, mirror_lag_bytes) or None if unavailable.

    Used bytes: total size of files on tmpfs.
    Mirror lag: difference between tmpfs audit size and disk backup audit size.
    A lag > 0 means some audit data hasn't been mirrored to disk yet.
    """
    if not _HAS_RAMDISK or not is_ramdisk_available():
        return None

    try:
        # Total tmpfs usage
        used = 0
        for dirpath, _dirnames, filenames in os.walk(RAMDISK_DIR):
            for f in filenames:
                try:
                    used += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass

        # Mirror lag: tmpfs audit size vs disk backup audit size
        tmpfs_audit_size = 0
        disk_audit_size = 0

        if os.path.isdir(TMPFS_AUDIT_DIR):
            for f in os.listdir(TMPFS_AUDIT_DIR):
                try:
                    tmpfs_audit_size += os.path.getsize(os.path.join(TMPFS_AUDIT_DIR, f))
                except OSError:
                    pass

        if os.path.isdir(BACKUP_AUDIT_DIR):
            for f in os.listdir(BACKUP_AUDIT_DIR):
                fp = os.path.join(BACKUP_AUDIT_DIR, f)
                # Only count .jsonl files (not .gz archives) for fair comparison
                if f.endswith(".jsonl"):
                    try:
                        disk_audit_size += os.path.getsize(fp)
                    except OSError:
                        pass

        lag = max(0, tmpfs_audit_size - disk_audit_size)
        return (used, lag)
    except (OSError, IOError):
        return None


def fmt_bytes(n):
    """Format bytes compactly: 1234 -> '1.2K', 4800000 -> '4.6M'."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}K"
    return f"{n / (1024 * 1024):.1f}M"


def calculate_health(gate_count, mem_count, session_state=None):
    """Calculate framework health as a weighted percentage (0-100).

    Dimensions (all lightweight filesystem checks):
      Gates present     (25%) — gate files vs expected
      Hooks registered  (20%) — hook events in settings vs expected
      Memory accessible (15%) — LanceDB has memories
      Skills present    (15%) — skill directories vs expected
      Core files exist  (15%) — CLAUDE.md, LIVE_STATE.json, enforcer.py
      Error pressure    (10%) — low errors in session state
    """
    if session_state is None:
        session_state = {}
    scores = {}

    # 1. Gates (25%) — ratio of actual to expected
    scores["gates"] = (min(gate_count / EXPECTED_GATES, 1.0), 25)

    # 2. Hooks (20%) — ratio of registered hook events
    hook_count = count_hook_events()
    scores["hooks"] = (min(hook_count / EXPECTED_HOOK_EVENTS, 1.0), 20)

    # 3. Memory (15%) — binary: accessible and has entries
    if isinstance(mem_count, int) and mem_count > 0:
        scores["memory"] = (1.0, 15)
    elif mem_count == "?":
        scores["memory"] = (0.0, 15)
    else:
        scores["memory"] = (0.5, 15)  # accessible but empty

    # 4. Skills (15%) — ratio of actual to expected
    skill_count = count_skills()
    scores["skills"] = (min(skill_count / EXPECTED_SKILLS, 1.0), 15)

    # 5. Core files (15%) — 3 essential files
    core_files = [
        os.path.join(CLAUDE_DIR, "CLAUDE.md"),
        LIVE_STATE_FILE,
        os.path.join(HOOKS_DIR, "enforcer.py"),
    ]
    core_present = sum(1 for f in core_files if os.path.isfile(f))
    scores["core"] = (core_present / len(core_files), 15)

    # 6. Error pressure (10%) — velocity-aware: recent errors heavily penalized
    try:
        recent_errors, total_errors = get_error_velocity(session_state)
        if recent_errors > 0:
            # Active error loop — use recent count with harsh penalties
            if recent_errors <= 2:
                scores["errors"] = (0.6, 10)
            elif recent_errors <= 5:
                scores["errors"] = (0.3, 10)
            else:
                scores["errors"] = (0.1, 10)
        elif total_errors > 0:
            # Historical errors but not recent — mild penalty
            scores["errors"] = (0.8, 10)
        else:
            # No errors — perfect health
            scores["errors"] = (1.0, 10)
    except Exception:
        # Fail-open on velocity calculation error
        scores["errors"] = (1.0, 10)

    # Weighted average
    total = sum(score * weight for score, weight in scores.values())
    max_total = sum(weight for _, weight in scores.values())
    return int(total / max_total * 100)


def health_color(pct):
    """Return ANSI color code based on health percentage.

    100%:  cyan    — perfect, everything present
    90-99: green   — healthy, minor issues
    75-89: orange  — warning, notable degradation
    50-74: yellow  — degraded, needs attention
    <50:   red     — critical, major components missing
    """
    if pct >= 100:
        return COLOR_CYAN
    if pct >= 90:
        return COLOR_GREEN
    if pct >= 75:
        return COLOR_ORANGE
    if pct >= 50:
        return COLOR_YELLOW
    return COLOR_RED


def get_git_branch():
    """Get current git branch name, cached for 10 seconds via /tmp file."""
    cache_file = "/tmp/statusline-git-cache"
    try:
        if os.path.exists(cache_file):
            age = time.time() - os.path.getmtime(cache_file)
            if age < 10:
                with open(cache_file) as f:
                    return f.read().strip() or None
    except OSError:
        pass
    # Cache miss — run git
    import subprocess
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=2
        )
        branch = result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        branch = None
    # Write cache
    try:
        with open(cache_file, "w") as f:
            f.write(branch or "")
    except OSError:
        pass
    return branch


def format_health_bar(pct):
    """Format health as a gradient bar using fg/bg half-block trick.

    Same visual technique as format_context_bar(): each character shows
    2 gradient segments (left=fg, right=bg) via U+258C. 10 chars = 20 segments.
    Positional gradient reversed from CTX: red(0%) → green(100%).
    """
    chars = 10       # physical character width
    segments = 20    # logical segments (2 per char via fg/bg)
    filled = round(pct / 100 * segments)
    filled = max(0, min(segments, filled))

    bar = ""
    for i in range(chars):
        left = 2 * i
        right = 2 * i + 1
        left_pct = (left / segments) * 100
        right_pct = (right / segments) * 100
        left_filled = left < filled
        right_filled = right < filled

        if left_filled and right_filled:
            fg = _hp_gradient_color(left_pct)
            bg = _hp_gradient_bg(right_pct)
            bar += f"{fg}{bg}\u258c{COLOR_RESET}"
        elif left_filled and not right_filled:
            fg = _hp_gradient_color(left_pct)
            bar += f"{fg}{_BG_DARK}\u258c{COLOR_RESET}"
        else:
            bar += f"{COLOR_DARK_GRAY}{_BG_DARK}\u258c{COLOR_RESET}"

    pct_color = _hp_gradient_color(pct)
    pct_str = f"{pct_color}{pct}%{COLOR_RESET}"
    return f"HP:{bar} {pct_str}"


def format_context_pct(pct):
    """Format context percentage with color coding (no bar).

    Cyan <40%, green 40-49%, orange 50-59%, yellow 60-69%, red 70%+.
    Returns: '{color}62%{reset}'
    """
    if pct >= 70:
        color = COLOR_RED
    elif pct >= 60:
        color = COLOR_YELLOW
    elif pct >= 50:
        color = COLOR_ORANGE
    elif pct >= 40:
        color = COLOR_GREEN
    else:
        color = COLOR_CYAN
    return f"{color}{int(pct)}%{COLOR_RESET}"


# Compaction threshold — Claude Code compacts around 90-95% context usage
COMPACTION_THRESHOLD = 93
COLOR_DIM = "\033[90m"
COLOR_DARK_GRAY = "\033[38;5;238m"

# Smooth gradient using 256-color ANSI — matches Anthropic console style
# Each entry is (threshold_pct, ansi_256_color_code)
_CTX_GRADIENT = [
    (0,  82),   # bright green
    (15, 76),   # green
    (25, 112),  # yellow-green
    (35, 148),  # light yellow-green
    (45, 184),  # yellow
    (55, 220),  # golden yellow
    (65, 214),  # light orange
    (75, 208),  # orange
    (85, 202),  # dark orange
    (92, 196),  # red
]


def _gradient_color(segment_pct):
    """Return ANSI 256-color escape for a position in the gradient."""
    code = _CTX_GRADIENT[0][1]
    for threshold, c in _CTX_GRADIENT:
        if segment_pct >= threshold:
            code = c
    return f"\033[38;5;{code}m"


def _gradient_bg(segment_pct):
    """Return ANSI 256-color background escape for a position in the gradient."""
    code = _CTX_GRADIENT[0][1]
    for threshold, c in _CTX_GRADIENT:
        if segment_pct >= threshold:
            code = c
    return f"\033[48;5;{code}m"


_BG_DARK = "\033[48;5;236m"

# HP gradient: reversed — red(0%) → green(100%), so full health = green end
_HP_GRADIENT = [
    (0,  196),  # red
    (8,  202),  # dark orange
    (15, 208),  # orange
    (25, 214),  # light orange
    (35, 220),  # golden yellow
    (45, 184),  # yellow
    (55, 148),  # light yellow-green
    (65, 112),  # yellow-green
    (75, 76),   # green
    (85, 82),   # bright green
]


def _hp_gradient_color(segment_pct):
    """Return ANSI 256-color foreground for HP bar position (red→green)."""
    code = _HP_GRADIENT[0][1]
    for threshold, c in _HP_GRADIENT:
        if segment_pct >= threshold:
            code = c
    return f"\033[38;5;{code}m"


def _hp_gradient_bg(segment_pct):
    """Return ANSI 256-color background for HP bar position (red→green)."""
    code = _HP_GRADIENT[0][1]
    for threshold, c in _HP_GRADIENT:
        if segment_pct >= threshold:
            code = c
    return f"\033[48;5;{code}m"


def format_context_bar(pct, cmp_count=0):
    """Format context usage as a smooth gradient bar matching Anthropic's console.

    Uses fg/bg half-block trick: each character shows 2 gradient segments
    (left half = foreground, right half = background). 10 chars = 20 segments.
    Compaction threshold marked at ~93%.
    """
    chars = 10       # physical character width (matches HP bar)
    segments = 20    # logical segments (2 per char via fg/bg)
    filled = round(pct / 100 * segments)
    filled = max(0, min(segments, filled))
    comp_seg = round(COMPACTION_THRESHOLD / 100 * segments)  # ~18

    bar = ""
    for i in range(chars):
        left = 2 * i        # left sub-segment index
        right = 2 * i + 1   # right sub-segment index
        left_pct = (left / segments) * 100
        right_pct = (right / segments) * 100
        left_filled = left < filled
        right_filled = right < filled

        # Compaction marker: if either sub-segment is the threshold
        if left == comp_seg or right == comp_seg:
            if left_filled:
                bar += f"\033[38;5;255m\033[48;5;236m\u2502{COLOR_RESET}"
            else:
                bar += f"\033[38;5;242m{_BG_DARK}\u2502{COLOR_RESET}"
        elif left_filled and right_filled:
            # Both halves filled — fg=left color, bg=right color
            fg = _gradient_color(left_pct)
            bg = _gradient_bg(right_pct)
            bar += f"{fg}{bg}\u258c{COLOR_RESET}"
        elif left_filled and not right_filled:
            # Left filled, right empty — fg=gradient, bg=dark
            fg = _gradient_color(left_pct)
            bar += f"{fg}{_BG_DARK}\u258c{COLOR_RESET}"
        else:
            # Both empty — dark
            bar += f"{COLOR_DARK_GRAY}{_BG_DARK}\u258c{COLOR_RESET}"

    pct_color = _gradient_color(pct)
    pct_str = f"{pct_color}{pct:.1f}%{COLOR_RESET}"
    cmp_str = f" CMP:{cmp_count}" if cmp_count > 0 else ""

    return f"CTX:{bar} {pct_str}{cmp_str}"


MEMORY_TS_FILE = os.path.join(HOOKS_DIR, ".memory_last_queried")
CTX_CACHE_FILE = "/tmp/statusline-ctx-cache"



def get_memory_freshness():
    """Return minutes since last memory query, or None if unknown."""
    try:
        with open(MEMORY_TS_FILE) as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        if ts <= 0:
            return None
        elapsed = int(time.time() - ts) // 60
        return elapsed
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_compression_count(current_pct, session_id=""):
    """Track context compression events by detecting significant % drops.

    Writes previous context % to a cache file. If current % drops by 10+
    points from previous, counts it as a compression event.
    Resets counter when session_id changes (new session detected).
    Returns compression count (0 if none detected).
    """
    prev_pct = 0
    count = 0
    cached_session = ""
    try:
        if os.path.exists(CTX_CACHE_FILE):
            with open(CTX_CACHE_FILE) as f:
                cache = json.load(f)
            cached_session = cache.get("session_id", "")
            # Reset on new session
            if session_id and cached_session and session_id != cached_session:
                prev_pct = 0
                count = 0
            else:
                prev_pct = cache.get("pct", 0)
                count = cache.get("compressions", 0)
    except (json.JSONDecodeError, OSError):
        pass

    # Detect compression: significant drop (10+ points) from previous reading
    if prev_pct > 0 and current_pct > 0 and (prev_pct - current_pct) >= 10:
        count += 1

    # Write current state
    try:
        with open(CTX_CACHE_FILE, "w") as f:
            json.dump({"pct": current_pct, "compressions": count, "session_id": session_id}, f)
    except OSError:
        pass
    return count


def main():
    # Force line-buffered stdout so each print() flushes immediately.
    # Without this, Python uses full buffering when stdout is a pipe (Claude Code),
    # and if the script is cancelled mid-execution, unflushed lines are lost.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass  # Python < 3.7

    # Read session data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    # Extract session info (correct nested paths)
    cost_data = data.get("cost", {}) or {}
    ctx_data = data.get("context_window", {}) or {}

    cost = cost_data.get("total_cost_usd", 0) or 0
    duration_ms = cost_data.get("total_duration_ms", 0) or 0
    lines_added = cost_data.get("total_lines_added", 0) or 0
    lines_removed = cost_data.get("total_lines_removed", 0) or 0
    context_pct = ctx_data.get("used_percentage", 0) or 0

    # Token counts — session totals
    total_in_tok = ctx_data.get("total_input_tokens", 0) or 0
    total_out_tok = ctx_data.get("total_output_tokens", 0) or 0
    session_tokens = total_in_tok + total_out_tok

    # Token counts — last turn (current_usage may be null early in session)
    cur_usage = ctx_data.get("current_usage", {}) or {}
    last_in_tok = cur_usage.get("input_tokens", 0) or 0
    last_out_tok = cur_usage.get("output_tokens", 0) or 0

    # Load session state once (used by all state-reading functions)
    sess_state = _load_session_state()

    # Calculate display values
    project = get_project_name()
    gate_count = count_gates()
    mem_count = get_memory_count()
    minutes = int(duration_ms / 60000) if duration_ms else 0

    # Format cost
    if isinstance(cost, (int, float)) and cost > 0:
        cost_str = f"${cost:.2f}"
    else:
        cost_str = "$0.00"

    # Format session tokens (combined input+output)
    if session_tokens > 0:
        session_tok_str = f"{fmt_tokens(session_tokens)} tok"
    else:
        session_tok_str = ""

    # Format last turn tokens (input>output)
    if last_in_tok or last_out_tok:
        last_tok_str = f"{fmt_tokens(last_in_tok)}>{fmt_tokens(last_out_tok)}"
    else:
        last_tok_str = ""

    # Format lines changed
    if lines_added or lines_removed:
        lines_str = f"+{lines_added}/-{lines_removed}"
    else:
        lines_str = ""

    # Calculate framework health
    health_pct = calculate_health(gate_count, mem_count, sess_state)

    # Model name from session data
    model_data = data.get("model", {}) or {}
    model_name = model_data.get("display_name", "Claude")
    # Detect model family from display name (case-insensitive substring match)
    model_lower = (model_name or "").lower()
    if "opus" in model_lower:
        model_short = "Opus"
        model_color = COLOR_DARK_ORANGE
    elif "sonnet" in model_lower:
        model_short = "Sonnet"
        model_color = "\033[94m"   # blue
    elif "haiku" in model_lower:
        model_short = "Haiku"
        model_color = "\033[97m"   # white
    else:
        model_short = model_name.split()[-1] if model_name else "Claude"
        model_color = COLOR_CYAN

    # Added directories (--add-dir)
    workspace_data = data.get("workspace", {}) or {}
    added_dirs = workspace_data.get("added_dirs", []) or []

    # Git branch
    git_branch = get_git_branch()

    # Skill count
    skill_count = count_skills()

    # Total tool calls
    total_calls = get_total_tool_calls(sess_state)

    # Health bar (10-char, same style as old context bar)
    health_bar = format_health_bar(health_pct)

    # ── LINE 1: Identity + framework health ──
    session_num = get_session_number()
    line1_parts = [f"{model_color}[{model_short}]{COLOR_RESET}"]

    # Active behavioral mode (right after model)
    active_mode = get_active_mode()
    if active_mode:
        line1_parts[0] += f" MODE:{active_mode}"

    # Active domain (knowledge overlay)
    active_domain = _get_active_domain()
    if active_domain:
        line1_parts[0] += f" DOM:{active_domain}"

    line1_parts.append(f"\U0001f4c1 {project}")
    if git_branch:
        line1_parts.append(f"\U0001f33f {git_branch}")
    if added_dirs:
        dir_names = [os.path.basename(d.rstrip("/")) for d in added_dirs]
        line1_parts.append(f"\U0001f4ce +{','.join(dir_names)}")
    line1_parts.append(f"#{session_num}")
    line1_parts.append(f"\U0001f6e1\ufe0f G:{gate_count} S:{skill_count}")
    # Memory count + freshness
    mem_fresh = get_memory_freshness()
    if mem_fresh is not None and mem_fresh > 0:
        line1_parts.append(f"\U0001f9e0 M:{mem_count} \u2191{mem_fresh}m")
    else:
        line1_parts.append(f"\U0001f9e0 M:{mem_count}")
    line1_parts.append(f"\u26a1TC:{total_calls}")

    # Subagent visibility (conditional, line 1)
    sa_active, sa_completed_tok = get_subagent_status(sess_state)
    if sa_active:
        sa_parts = []
        for agent_type, tok in sa_active:
            short_type = agent_type[:8]
            sa_parts.append(f"{short_type}({fmt_tokens(tok)})")
        line1_parts.append("SA:" + ",".join(sa_parts))

    # Ramdisk health (conditional, line 1)
    rd_health = get_ramdisk_health()
    if rd_health is not None:
        rd_used, rd_lag = rd_health
        rd_str = f"RD:{fmt_bytes(rd_used)}"
        if rd_lag > 1024:
            rd_str += f"|lag:{fmt_bytes(rd_lag)}"
        line1_parts.append(rd_str)

    # ── LINE 2: Health bar + context bar + session metrics ──
    ctx_pct_val = int(context_pct) if isinstance(context_pct, (int, float)) else 0
    session_id = data.get("session_id", "")
    cmp_count = get_compression_count(ctx_pct_val, session_id)
    ctx_bar = format_context_bar(ctx_pct_val, cmp_count)

    line2_parts = [health_bar, ctx_bar]

    # Error pressure (conditional — only when recent errors active)
    recent_errors, total_errors = get_error_velocity(sess_state)
    if recent_errors > 0:
        line2_parts.append(f"{COLOR_RED}E:{recent_errors}\U0001f525{COLOR_RESET}")
    elif total_errors > 0:
        line2_parts.append(f"{COLOR_YELLOW}\u26a0\ufe0fE:{total_errors}{COLOR_RESET}")

    # Session tokens + last turn breakdown
    if session_tok_str:
        tok_display = session_tok_str
        if last_tok_str:
            tok_display += f" ({last_tok_str})"
        line2_parts.append(tok_display)

    # Duration
    if minutes:
        line2_parts.append(f"\u23f1\ufe0f {minutes}m")

    # Lines changed
    if lines_str:
        line2_parts.append(lines_str)

    # Verification ratio (verified/total — pending is implicit: total - verified)
    vr_verified, vr_total = get_verification_ratio(sess_state)
    if vr_total > 0:
        line2_parts.append(f"\u2705V:{vr_verified}/{vr_total}")

    # Cost
    line2_parts.append(f"\U0001f4b0{cost_str}")

    # Plan mode escalation warnings (conditional, line 2 end)
    pm_warns = get_plan_mode_warns(sess_state)
    if pm_warns >= 1:
        line2_parts.append(f"PM:W{pm_warns}")

    print(" | ".join(line1_parts))
    print(" | ".join(line2_parts))

    # ── LINE 3: Toggle switches ──
    # Read toggles from config.json (canonical), fall back to LIVE_STATE.json
    config_file = os.path.join(CLAUDE_DIR, "config.json")
    try:
        with open(config_file) as f:
            ls = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        try:
            with open(LIVE_STATE_FILE) as f:
                ls = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            ls = {}

    def _tog(key, label, default=False):
        if ls.get(key, default):
            return f"{COLOR_GREEN}\u25c9 {label}{COLOR_RESET}"
        return f"\u25cb {label}"

    budget_val = ls.get("session_token_budget", 0) or 0
    # Compute budget tier for display
    budget_tier_str = ""
    if ls.get("budget_degradation") and budget_val > 0 and session_tokens > 0:
        usage_pct = session_tokens / budget_val
        if usage_pct >= 0.95:
            budget_tier_str = " \u2620\ufe0fDEAD"
        elif usage_pct >= 0.80:
            budget_tier_str = " \U0001f534CRIT"
        elif usage_pct >= 0.40:
            budget_tier_str = " \U0001f7e1LOW"
    line3 = (
        f"{_tog('terminal_l2_always', 'L2')} "
        f"{_tog('context_enrichment', 'Enrich')} "
        f"{_tog('transcript_l0', 'L0')} "
        f"{_tog('tg_l3_always', 'TG')} "
        f"{_tog('tg_enrichment', 'TGe')} "
        f"{_tog('tg_bot_tmux', 'Bot')} "
        f"{_tog('gate_auto_tune', 'Tune')} "
        f"{_tog('tg_session_notify', 'Notify')} "
        f"{_tog('tg_mirror_messages', 'Mirror')} "
        f"{_tog('budget_degradation', 'Budget')} "
        f"B:{budget_val}{budget_tier_str}"
    )
    print(line3)

    # ── LINE 4: Search routing mode ──
    _routing = ls.get("search_routing", "default")

    def _mode_label(key, label):
        if _routing == key:
            return f"{COLOR_GREEN}\u25c9 {label}{COLOR_RESET}"
        return f"\u25cb {label}"

    line4 = f"Memory: {_mode_label('default', 'Default')} {_mode_label('fast', 'Fast')} {_mode_label('full_hybrid', 'Full Hybrid')}"
    print(line4)

    # ── LINE 5: Model profile (radio select) ──
    _model_prof = ls.get("model_profile", "balanced")

    def _prof_label(key, label, active):
        if active == key:
            return f"{COLOR_GREEN}\u25c9 {label}{COLOR_RESET}"
        return f"\u25cb {label}"

    line5 = (
        f"Model: "
        f"{_prof_label('quality', 'Quality', _model_prof)} "
        f"{_prof_label('balanced', 'Balanced', _model_prof)} "
        f"{_prof_label('efficient', 'Efficient', _model_prof)} "
        f"{_prof_label('lean', 'Lean', _model_prof)} "
        f"{_prof_label('budget', 'Budget', _model_prof)}"
    )
    print(line5)

    # ── LINE 6: Security profile (radio select) ──
    _sec_prof = ls.get("security_profile", "balanced")
    line6 = (
        f"Security: "
        f"{_prof_label('strict', 'Strict', _sec_prof)} "
        f"{_prof_label('balanced', 'Balanced', _sec_prof)} "
        f"{_prof_label('permissive', 'Permissive', _sec_prof)} "
        f"{_prof_label('refactor', 'Refactor', _sec_prof)}"
    )
    print(line6)

    # ── LINE 7: Mentor system toggles ──
    line5 = (
        f"Mentor: "
        f"{_tog('mentor_all', 'All')} "
        f"{_tog('mentor_tracker', 'Tracker')} "
        f"{_tog('mentor_hindsight_gate', 'Hindsight')} "
        f"{_tog('mentor_outcome_chains', 'Chains')} "
        f"{_tog('mentor_memory', 'Memory')}"
    )
    print(line5)

    # Ensure all display lines are flushed before slow snapshot I/O
    sys.stdout.flush()

    # ── SNAPSHOT: write bridge file for TUI ──
    # Check UDS socket health
    uds_ok = False
    try:
        uds_ok = is_worker_available(retries=1, delay=0)
    except Exception:
        pass

    snapshot = {
        "ts": time.time(),
        "model": model_short,
        "cost_usd": cost if isinstance(cost, (int, float)) else 0,
        "duration_min": minutes,
        "context_pct": ctx_pct_val,
        "compressions": cmp_count,
        "session_tokens": fmt_tokens(session_tokens) if session_tokens > 0 else "0",
        "last_turn": last_tok_str or "",
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "health_pct": health_pct,
        "uds_ok": uds_ok,
    }
    snap_path = os.path.join(HOOKS_DIR, ".statusline_snapshot.json")
    snap_tmp = snap_path + ".tmp"
    try:
        with open(snap_tmp, "w") as f:
            json.dump(snapshot, f)
        os.replace(snap_tmp, snap_path)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: output minimal line on crash
        import traceback
        try:
            with open("/tmp/statusline_crash.log", "w") as _ef:
                traceback.print_exc(file=_ef)
        except Exception:
            pass
        print("claude | status error")
