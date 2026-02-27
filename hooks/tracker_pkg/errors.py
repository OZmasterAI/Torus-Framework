"""Error detection and pattern tracking for PostToolUse."""
import time


def _extract_error_pattern(tool_response):
    """Extract the primary error pattern from test output.

    Looks for common error signatures in test output and returns the first match.
    Returns "unknown" if no pattern found.
    """
    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "") + tool_response.get("stderr", "")
    elif isinstance(tool_response, str):
        output = tool_response
    else:
        return "unknown"

    ERROR_SIGS = [
        "Traceback", "SyntaxError:", "ImportError:", "ModuleNotFoundError:",
        "TypeError:", "ValueError:", "KeyError:", "AttributeError:",
        "AssertionError:", "NameError:", "FAILED", "npm ERR!", "fatal:",
    ]
    for sig in ERROR_SIGS:
        if sig in output:
            return sig
    return "unknown"


def _deduplicate_error_window(state, pattern):
    """Windowed error deduplication: group same patterns within 60s windows.

    Tracks (pattern, first_seen, last_seen, count) tuples in state["error_windows"].
    If same error pattern appears within 60s, increments count instead of adding new entry.
    Caps at 50 unique patterns.
    """
    now = time.time()
    windows = state.setdefault("error_windows", [])

    # Check for existing window for this pattern
    for window in windows:
        if window["pattern"] == pattern and (now - window["last_seen"]) <= 60:
            window["last_seen"] = now
            window["count"] += 1
            return  # Deduplicated — no new entry needed

    # No recent window found — create new one (cap at 50)
    if len(windows) >= 50:
        # Remove oldest window
        windows.sort(key=lambda w: w["last_seen"])
        windows.pop(0)

    windows.append({
        "pattern": pattern,
        "first_seen": now,
        "last_seen": now,
        "count": 1,
    })


def _detect_errors(tool_input, tool_response, state):
    """Scan Bash output for error patterns, track in state."""
    ERROR_PATTERNS = [
        "Traceback", "SyntaxError:", "ImportError:", "ModuleNotFoundError:",
        "Permission denied", "npm ERR!", "fatal:", "error[E", "FAILED",
        "command not found", "No such file or directory",
        "ConnectionRefusedError", "OSError:",
    ]
    # Handle both string and dict tool_response defensively
    if isinstance(tool_response, dict):
        output = tool_response.get("stdout", "") + tool_response.get("stderr", "")
    else:
        output = str(tool_response)

    command = tool_input.get("command", "")
    for pattern in ERROR_PATTERNS:
        if pattern in output:
            entry = {"pattern": pattern, "command": command, "timestamp": time.time()}
            state.setdefault("unlogged_errors", []).append(entry)
            # Track pattern recurrence for repair loop detection
            counts = state.setdefault("error_pattern_counts", {})
            counts[pattern] = counts.get(pattern, 0) + 1
            # Windowed deduplication
            _deduplicate_error_window(state, pattern)
            break  # One entry per Bash tool call max
