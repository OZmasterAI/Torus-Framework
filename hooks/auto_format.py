#!/usr/bin/env python3
"""PostToolUse hook — auto-format Python files after Edit or Write.

Reads the hook event from stdin, checks if the tool was Edit or Write on a
.py file, then runs `ruff format` (falling back to `black`) on that file.

Fail-open: always exits 0.  A formatting failure must never block work.
Timeout-safe: formatter subprocess is capped at 3 seconds.

Usage (wired in settings.json PostToolUse):
    echo '<hook-json>' | python3 auto_format.py
"""

import json
import os
import subprocess
import sys

# ── constants ──────────────────────────────────────────────────────────────
TRIGGER_TOOLS = {"Edit", "Write"}
FORMAT_TIMEOUT = 3  # seconds


# ── helpers ────────────────────────────────────────────────────────────────

def _run_formatter(file_path: str) -> tuple[bool, str]:
    """Try ruff format, fall back to black.  Return (success, tool_used)."""
    for cmd in (["ruff", "format", "--quiet", file_path],
                ["black", "--quiet", file_path]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=FORMAT_TIMEOUT,
            )
            if result.returncode == 0:
                return True, cmd[0]
        except FileNotFoundError:
            # formatter not installed — try next
            continue
        except subprocess.TimeoutExpired:
            # timed out — skip silently
            return False, cmd[0]
        except Exception:
            continue
    return False, "none"


def main() -> None:
    # ── parse stdin ────────────────────────────────────────────────────────
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    # tool_input may arrive pre-parsed or as a JSON string
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except Exception:
            tool_input = {}

    # ── guard: only Edit / Write ───────────────────────────────────────────
    if tool_name not in TRIGGER_TOOLS:
        return

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    # ── guard: only .py files ─────────────────────────────────────────────
    if not file_path.endswith(".py"):
        return

    # ── guard: file must exist (Write creates it; race is benign) ─────────
    if not os.path.isfile(file_path):
        return

    # ── format ────────────────────────────────────────────────────────────
    _run_formatter(file_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
