"""Common gate utility helpers — shared/gate_helpers.py

Extracts repeated patterns from gate files into reusable functions:
- File path extraction and classification
- Test file detection
- Tool input normalization
- Gate early-return helpers

All functions are pure, stateless, and safe to call from any context.

Public API
----------
  extract_file_path(tool_input)           -> str
  is_test_file(file_path)                 -> bool
  stem_normalize(file_path)               -> str
  is_related_file(path_a, path_b)         -> bool
  safe_tool_input(tool_input)             -> dict
  extract_command(tool_input)             -> str
  is_edit_tool(tool_name)                 -> bool
  file_extension(file_path)               -> str
  elapsed_since(timestamp)                -> float
  is_stale(timestamp, window_seconds)     -> bool

Usage
-----
    from shared.gate_helpers import (
        extract_file_path, is_test_file, safe_tool_input,
        is_edit_tool, elapsed_since, is_stale,
    )
"""

import os
import time
from typing import Optional


# ---------------------------------------------------------------------------
# File path utilities
# ---------------------------------------------------------------------------


def extract_file_path(tool_input: dict) -> str:
    """Extract the primary file path from a tool_input dict.

    Checks file_path, notebook_path, and path fields in order.
    Returns empty string if no path found or input is not a dict.

    Args:
        tool_input: The tool_input dict from a hook payload.

    Returns:
        The extracted file path string, or "".
    """
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "notebook_path", "path"):
        val = tool_input.get(key, "")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def is_test_file(file_path: str) -> bool:
    """Check if a file path refers to a test file.

    Matches common test file patterns:
    - test_*.py, *_test.py, *_spec.py
    - *.test.js, *.spec.ts, etc.

    Args:
        file_path: Absolute or relative file path.

    Returns:
        True if the file appears to be a test file.
    """
    if not file_path:
        return False
    basename = os.path.basename(file_path)
    stem = os.path.splitext(basename)[0]
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith("_spec")
        or stem.endswith(".test")
        or stem.endswith(".spec")
        or basename.startswith("test_")
    )


def stem_normalize(file_path: str) -> str:
    """Normalize a file path to its canonical stem for matching.

    Strips test prefixes (test_, test) and test suffixes (_test, _spec,
    .test, .spec) so that 'foo.py' and 'test_foo.py' share the same
    normalized stem.

    Args:
        file_path: File path to normalize.

    Returns:
        Lowercased normalized stem string.
    """
    if not file_path:
        return ""
    stem = os.path.splitext(os.path.basename(file_path))[0]
    # Strip test prefixes
    for prefix in ("test_", "test"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    # Strip test suffixes
    for suffix in ("_test", "_spec", ".test", ".spec"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    return stem.lower()


def is_related_file(path_a: str, path_b: str) -> bool:
    """Check if two file paths are semantically related.

    Related means either:
    - Same basename (same file in different directory)
    - Same normalized stem (e.g., foo.py <-> test_foo.py)

    Args:
        path_a: First file path.
        path_b: Second file path.

    Returns:
        True if the files are related.
    """
    if not path_a or not path_b:
        return False
    if os.path.basename(path_a) == os.path.basename(path_b):
        return True
    return stem_normalize(path_a) == stem_normalize(path_b)


# ---------------------------------------------------------------------------
# Tool input utilities
# ---------------------------------------------------------------------------


def safe_tool_input(tool_input) -> dict:
    """Ensure tool_input is a dict, converting non-dicts to empty dict.

    Args:
        tool_input: Raw tool input (may be None, str, or dict).

    Returns:
        The input as a dict, or {} if it wasn't a dict.
    """
    if isinstance(tool_input, dict):
        return tool_input
    return {}


def extract_command(tool_input: dict) -> str:
    """Extract the command string from a Bash tool_input.

    Args:
        tool_input: The tool_input dict.

    Returns:
        The command string, or "" if not found.
    """
    if not isinstance(tool_input, dict):
        return ""
    cmd = tool_input.get("command", "")
    return cmd if isinstance(cmd, str) else ""


def is_edit_tool(tool_name: str) -> bool:
    """Check if the tool name is a file-editing tool.

    Args:
        tool_name: The tool name string.

    Returns:
        True if the tool is Edit, Write, or NotebookEdit.
    """
    return tool_name in ("Edit", "Write", "NotebookEdit")


def file_extension(file_path: str) -> str:
    """Extract the file extension (lowercased, with dot).

    Args:
        file_path: File path string.

    Returns:
        Extension like ".py", ".js", or "" if none.
    """
    if not file_path:
        return ""
    return os.path.splitext(file_path)[1].lower()


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------


def elapsed_since(timestamp: float) -> float:
    """Compute seconds elapsed since a given Unix timestamp.

    Args:
        timestamp: Unix timestamp (seconds since epoch).

    Returns:
        Seconds elapsed. Returns 0.0 if timestamp is 0 or in the future.
    """
    if not timestamp or timestamp <= 0:
        return 0.0
    elapsed = time.time() - timestamp
    return max(0.0, elapsed)


def is_stale(timestamp: float, window_seconds: float) -> bool:
    """Check if a timestamp is older than the given window.

    Args:
        timestamp: Unix timestamp to check.
        window_seconds: Maximum age in seconds.

    Returns:
        True if the timestamp is older than window_seconds ago,
        or if timestamp is 0/missing.
    """
    if not timestamp or timestamp <= 0:
        return True
    return elapsed_since(timestamp) > window_seconds
