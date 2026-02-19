"""Observation capture and deduplication for PostToolUse."""
import json
import os

from shared.error_normalizer import fnv1a_hash
from tracker_pkg import _log_debug
from tracker_pkg.auto_remember import CAPTURABLE_TOOLS, CAPTURE_QUEUE, _cap_queue_file


def _observation_key(tool_name, tool_input):
    """Generate a deduplication key for an observation based on tool and key inputs.

    Returns a string that represents the essential identity of this observation.
    """
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")[:200]
        return f"Bash:{cmd}"
    elif tool_name == "Read":
        fp = tool_input.get("file_path", "")
        return f"Read:{fp}"
    elif tool_name in ("Edit", "Write"):
        fp = tool_input.get("file_path", "")
        # Include content hash so different edits to the same file are not deduplicated
        if tool_name == "Edit":
            content_snippet = tool_input.get("old_string", "")[:100]
        else:
            content_snippet = tool_input.get("content", "")[:100]
        if content_snippet:
            content_hash = fnv1a_hash(content_snippet)
            return f"{tool_name}:{fp}:{content_hash}"
        return f"{tool_name}:{fp}"
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"Glob:{pattern}"
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"Grep:{pattern}:{path}"
    elif tool_name == "WebSearch":
        query = tool_input.get("query", "")[:100]
        return f"WebSearch:{query}"
    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")
        return f"WebFetch:{url}"
    else:
        return tool_name


def _is_recent_duplicate(obs_hash):
    """Check if an observation hash appears in the last 20 lines of the queue.

    Returns True if duplicate found, False otherwise.
    Fail-open: any exception returns False (allow capture).
    """
    try:
        if not os.path.exists(CAPTURE_QUEUE):
            return False

        with open(CAPTURE_QUEUE, "r") as f:
            lines = f.readlines()

        # Check last 20 lines
        for line in lines[-20:]:
            try:
                obs = json.loads(line)
                if obs.get("_obs_hash") == obs_hash:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue

        return False
    except Exception:
        return False  # Fail-open: allow capture on any error


def _capture_observation(tool_name, tool_input, tool_response, session_id, state):
    """Append observation to queue file. Never raises — capture must not crash tracker."""
    try:
        if tool_name not in CAPTURABLE_TOOLS:
            return

        # Near-duplicate detection
        obs_hash = None
        try:
            obs_key = _observation_key(tool_name, tool_input)
            obs_hash = fnv1a_hash(obs_key)

            if _is_recent_duplicate(obs_hash):
                return  # Skip duplicate observation
        except Exception as e:
            _log_debug(f"dedup check failed (allowing capture): {e}")
            obs_hash = None  # Fail-open: continue with capture

        from shared.observation import compress_observation
        obs = compress_observation(tool_name, tool_input, tool_response, session_id, state=state)

        # Add dedup hash to observation if we computed it
        if obs_hash is not None:
            obs["_obs_hash"] = obs_hash

        with open(CAPTURE_QUEUE, "a") as f:
            f.write(json.dumps(obs) + "\n")
        # Cap check every 50 calls
        if state.get("tool_call_count", 0) % 50 == 0:
            _cap_queue_file()
    except Exception as e:
        _log_debug(f"capture_observation failed: {e}")
