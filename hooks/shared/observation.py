"""Observation compression for auto-capture system.

Compresses tool call data into compact text summaries suitable for
ChromaDB storage. Applies secrets scrubbing before any content is stored.

Each observation gets a deterministic ID (obs_{hash}) for dedup.
"""

import hashlib
import json
import time
from datetime import datetime

from shared.secrets_filter import scrub

# Import fnv1a_hash for command dedup
try:
    from shared.error_normalizer import fnv1a_hash
except ImportError:
    def fnv1a_hash(text):
        h = 14695981039346656037
        for byte in text.encode('utf-8'):
            h ^= byte
            h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        return format(h, '016x')[:8]


# Tools worth capturing (high signal)
CAPTURABLE_TOOLS = {"Bash", "Edit", "Write", "NotebookEdit", "UserPrompt"}

# Error patterns to detect in Bash output
_ERROR_PATTERNS = [
    "Traceback", "SyntaxError:", "ImportError:", "ModuleNotFoundError:",
    "Permission denied", "npm ERR!", "fatal:", "error[E", "FAILED",
    "command not found", "No such file or directory",
    "ConnectionRefusedError", "OSError:",
    # Common Python exceptions
    "AssertionError:", "KeyError:", "ValueError:", "TypeError:",
    "AttributeError:", "IndexError:", "NameError:", "FileNotFoundError:",
    "RuntimeError:", "TimeoutError:",
    # Test and build failures
    "pytest FAILED", "test failed", "ERRORS:", "CalledProcessError",
    # System-level errors
    "panic:", "segmentation fault", "core dumped", "killed",
]


def _detect_error_pattern(output: str) -> str:
    """Return the first matching error pattern, or empty string."""
    for pattern in _ERROR_PATTERNS:
        if pattern in output:
            return pattern
    return ""


def _extract_exit_code(tool_response) -> str:
    """Extract exit code from tool_response (str or dict)."""
    if isinstance(tool_response, dict):
        return str(tool_response.get("exit_code",
                   tool_response.get("exitCode",
                   tool_response.get("status", ""))))
    if isinstance(tool_response, str):
        try:
            resp = json.loads(tool_response)
            if isinstance(resp, dict):
                return str(resp.get("exit_code",
                           resp.get("exitCode",
                           resp.get("status", ""))))
        except (json.JSONDecodeError, TypeError):
            pass
    return ""


def _get_output_text(tool_response) -> str:
    """Extract text output from tool_response."""
    if isinstance(tool_response, dict):
        stdout = tool_response.get("stdout", "")
        stderr = tool_response.get("stderr", "")
        return f"{stdout}\n{stderr}".strip() if stderr else str(stdout)
    if isinstance(tool_response, str):
        return tool_response
    return str(tool_response) if tool_response else ""


def _extract_command_name(command):
    """Extract the first meaningful command name from a shell command string."""
    if not command:
        return ""
    # Strip leading env vars, sudo, etc.
    parts = command.strip().split()
    skip_prefixes = {"sudo", "env", "nohup", "time", "nice"}
    for part in parts:
        if "=" in part:
            continue  # env var assignment
        if part in skip_prefixes:
            continue
        return part.split("/")[-1]  # basename
    return parts[0] if parts else ""


def _extract_file_extension(file_path):
    """Extract file extension from a path."""
    if not file_path:
        return ""
    import os
    _, ext = os.path.splitext(file_path)
    return ext


def _compute_priority(tool_name, has_error, exit_code):
    """Compute observation priority: high for errors, medium for edits, low for reads."""
    if has_error or (exit_code and exit_code not in ("", "0")):
        return "high"
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return "medium"
    if tool_name in ("Read", "Glob", "Grep"):
        return "low"
    if tool_name in ("Bash", "WebSearch", "WebFetch"):
        return "medium"
    return "low"


def _detect_sentiment(tool_name, tool_input, state):
    """Detect agent sentiment from tool usage patterns and state.

    Returns a sentiment string or empty string for neutral.
    """
    if state is None:
        return ""

    # Frustration: repeated error patterns while editing
    if tool_name in ("Edit", "Write"):
        counts = state.get("error_pattern_counts", {})
        if any(v >= 2 for v in counts.values()):
            return "frustration"

    # Confidence: recent passing tests
    if state.get("last_test_exit_code") == 0:
        if (time.time() - state.get("last_test_run", 0)) < 120:
            return "confidence"

    # Exploration: read/search tools
    if tool_name in ("Read", "Grep", "Glob", "WebSearch", "WebFetch"):
        return "exploration"

    return ""


def compress_observation(tool_name, tool_input, tool_response, session_id, state=None):
    """Compress a tool call into a compact observation dict.

    Returns dict with 'document', 'metadata', and 'id' keys,
    ready for queue append or ChromaDB upsert.
    Includes tool-specific context metadata and priority scoring.
    """
    now = time.time()
    timestamp = datetime.now().isoformat()
    has_error = False
    error_pattern = ""
    exit_code = ""
    command_hash = ""
    context = {}

    if tool_name == "Bash":
        command = scrub(str(tool_input.get("command", ""))[:200])
        output_text = scrub(_get_output_text(tool_response)[:300])
        exit_code = _extract_exit_code(tool_response)
        error_pattern = _detect_error_pattern(_get_output_text(tool_response))
        has_error = bool(error_pattern) or (exit_code and exit_code not in ("", "0"))
        command_hash = fnv1a_hash(tool_input.get("command", ""))
        document = f"Bash: {command} → EXIT {exit_code} | {error_pattern} | {output_text}"
        context = {
            "exit_code": exit_code,
            "cmd": _extract_command_name(tool_input.get("command", "")),
            "cwd": tool_input.get("cwd", ""),
        }
        if error_pattern:
            context["error_pattern"] = error_pattern

    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        old_str = tool_input.get("old_string", "")
        # Approximate line range from old_string length
        lines_hint = old_str.count('\n') + 1 if old_str else 0
        document = f"Edit: {file_path} (~{lines_hint} lines changed)"
        context = {
            "file_path": file_path,
            "file_extension": _extract_file_extension(file_path),
        }

    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        document = f"Write: {file_path} ({len(content)} chars)"
        context = {
            "file_path": file_path,
            "file_extension": _extract_file_extension(file_path),
        }

    elif tool_name == "NotebookEdit":
        notebook_path = tool_input.get("notebook_path", "")
        cell_number = tool_input.get("cell_number", "?")
        edit_mode = tool_input.get("edit_mode", "replace")
        document = f"NotebookEdit: {notebook_path} cell {cell_number} ({edit_mode})"
        context = {
            "file_path": notebook_path,
            "file_extension": _extract_file_extension(notebook_path),
        }

    elif tool_name == "UserPrompt":
        prompt_text = scrub(str(tool_input.get("prompt", ""))[:200])
        document = f"UserPrompt: {prompt_text}"

    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        context = {
            "file_path": file_path,
            "file_extension": _extract_file_extension(file_path),
        }
        document = f"Read: {file_path}"

    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        context = {
            "pattern": pattern,
            "path": path,
        }
        document = f"{tool_name}: {pattern} in {path or '.'}"

    elif tool_name == "Skill":
        skill_name = tool_input.get("skill", "") or tool_input.get("name", "")
        context = {"skill_name": skill_name}
        document = f"Skill: {skill_name}"

    elif tool_name == "WebSearch":
        query = tool_input.get("query", "")
        context = {"query": query}
        document = f"WebSearch: {query[:100]}"

    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")
        context = {"url": url}
        document = f"WebFetch: {url}"

    elif tool_name == "Task":
        description = tool_input.get("description", "")
        subagent_type = tool_input.get("subagent_type", "")
        model = tool_input.get("model", "")
        document = f"Task: {subagent_type} — {description[:80]}"
        if model:
            document += f" (model={model})"
        context = {"subagent_type": subagent_type, "model": model}
        priority = "medium"

    else:
        document = f"{tool_name}: (uncategorized)"

    priority = _compute_priority(tool_name, has_error, exit_code)

    # Detect agent sentiment
    sentiment = _detect_sentiment(tool_name, tool_input, state)

    # Generate deterministic ID
    id_source = f"{document}_{session_id}_{now}"
    obs_id = "obs_" + hashlib.sha256(id_source.encode()).hexdigest()[:12]

    return {
        "document": document,
        "metadata": {
            "tool_name": tool_name,
            "session_id": session_id,
            "session_time": now,
            "timestamp": timestamp,
            "has_error": "true" if has_error else "false",
            "error_pattern": error_pattern,
            "exit_code": exit_code,
            "command_hash": command_hash,
            "priority": priority,
            "sentiment": sentiment if sentiment else "",
            "context": json.dumps(context) if context else "",
        },
        "id": obs_id,
    }
