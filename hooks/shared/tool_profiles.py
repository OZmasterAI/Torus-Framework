"""Tool Profile Evolution — AutoAgent-inspired online adaptation.

Maintains per-tool profiles that evolve from observed usage:
- known_failures: error patterns seen for this tool
- preconditions: conditions that must hold before the tool succeeds
- success_rate: rolling success/failure ratio
- common_args: frequently used argument patterns

Profiles persist across sessions via JSON file on ramdisk with disk mirror.
"""

import json
import os
import time

_RAMDISK_DIR = f"/run/user/{os.getuid()}/claude-hooks"
_DISK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".state")
_PROFILES_FILENAME = "tool_profiles.json"

# Tools worth profiling (high-frequency tools with failure modes)
PROFILED_TOOLS = {
    "Edit",
    "Write",
    "Bash",
    "Read",
    "Grep",
    "Glob",
    "NotebookEdit",
    "Agent",
    "Skill",
}

# Max entries per profile field to prevent unbounded growth
MAX_KNOWN_FAILURES = 30
MAX_PRECONDITIONS = 15
MAX_COMMON_ERRORS = 20

# Rolling window for success rate (last N calls)
RATE_WINDOW = 50


def _profiles_path():
    """Return best available path (ramdisk preferred, disk fallback)."""
    ramdisk = os.path.join(_RAMDISK_DIR, _PROFILES_FILENAME)
    disk = os.path.join(_DISK_DIR, _PROFILES_FILENAME)
    if os.path.isdir(_RAMDISK_DIR):
        return ramdisk, disk
    return disk, None


def load_profiles():
    """Load tool profiles from persistent storage."""
    primary, fallback = _profiles_path()
    for path in (primary, fallback):
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
    return {}


def save_profiles(profiles):
    """Save tool profiles to persistent storage (ramdisk + disk mirror)."""
    primary, mirror = _profiles_path()
    data = json.dumps(profiles, indent=2)
    for path in (primary, mirror):
        if path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(data)
            except IOError:
                pass


def get_profile(profiles, tool_name):
    """Get or create a profile for a tool."""
    if tool_name not in profiles:
        profiles[tool_name] = {
            "known_failures": [],
            "preconditions": [],
            "success_count": 0,
            "failure_count": 0,
            "recent_outcomes": [],  # list of {"success": bool, "ts": float}
            "common_errors": [],  # list of {"pattern": str, "count": int, "last_seen": float}
            "last_updated": time.time(),
        }
    return profiles[tool_name]


def record_success(profiles, tool_name, tool_input):
    """Record a successful tool call."""
    if tool_name not in PROFILED_TOOLS:
        return
    profile = get_profile(profiles, tool_name)
    profile["success_count"] += 1
    _add_outcome(profile, True)
    profile["last_updated"] = time.time()


def record_failure(profiles, tool_name, tool_input, error_text):
    """Record a failed tool call and extract learnable patterns.

    Returns a dict with extracted info if a NEW failure pattern was learned,
    None otherwise.
    """
    if tool_name not in PROFILED_TOOLS:
        return None
    profile = get_profile(profiles, tool_name)
    profile["failure_count"] += 1
    _add_outcome(profile, False)
    profile["last_updated"] = time.time()

    # Extract error signature (first meaningful line of error)
    error_sig = _extract_error_signature(error_text)
    if not error_sig:
        return None

    # Check if this is a known failure
    for known in profile["known_failures"]:
        if known["signature"] == error_sig:
            known["count"] += 1
            known["last_seen"] = time.time()
            return None  # Already known

    # New failure pattern discovered
    context = _extract_failure_context(tool_name, tool_input)
    entry = {
        "signature": error_sig,
        "context": context,
        "count": 1,
        "first_seen": time.time(),
        "last_seen": time.time(),
    }
    profile["known_failures"].append(entry)

    # Cap at max
    if len(profile["known_failures"]) > MAX_KNOWN_FAILURES:
        # Remove least-seen entries
        profile["known_failures"].sort(key=lambda x: x["count"], reverse=True)
        profile["known_failures"] = profile["known_failures"][:MAX_KNOWN_FAILURES]

    # Update common_errors aggregate
    _update_common_errors(profile, error_sig)

    return {
        "tool": tool_name,
        "signature": error_sig,
        "context": context,
        "is_new": True,
    }


def add_precondition(profiles, tool_name, precondition):
    """Add a learned precondition to a tool's profile."""
    profile = get_profile(profiles, tool_name)
    # Avoid duplicates (fuzzy match on first 50 chars)
    prefix = precondition[:50].lower()
    for existing in profile["preconditions"]:
        if existing["text"][:50].lower() == prefix:
            existing["reinforced"] += 1
            existing["last_seen"] = time.time()
            return False  # Already exists

    profile["preconditions"].append(
        {
            "text": precondition,
            "source": "learned",
            "reinforced": 1,
            "first_seen": time.time(),
            "last_seen": time.time(),
        }
    )

    if len(profile["preconditions"]) > MAX_PRECONDITIONS:
        # Keep most reinforced
        profile["preconditions"].sort(key=lambda x: x["reinforced"], reverse=True)
        profile["preconditions"] = profile["preconditions"][:MAX_PRECONDITIONS]

    profile["last_updated"] = time.time()
    return True


def get_success_rate(profile):
    """Compute rolling success rate from recent outcomes."""
    outcomes = profile.get("recent_outcomes", [])
    if not outcomes:
        total = profile.get("success_count", 0) + profile.get("failure_count", 0)
        if total == 0:
            return 1.0  # No data = assume good
        return profile.get("success_count", 0) / total
    successes = sum(1 for o in outcomes if o.get("success"))
    return successes / len(outcomes) if outcomes else 1.0


def get_warnings_for_tool(profiles, tool_name, tool_input):
    """Check tool input against known failures and preconditions.

    Returns list of warning strings (empty = no concerns).
    """
    if tool_name not in profiles:
        return []
    profile = profiles[tool_name]
    warnings = []

    # Check known failures that match current context
    context = _extract_failure_context(tool_name, tool_input)
    for failure in profile.get("known_failures", []):
        if failure["count"] >= 2 and _context_matches(
            failure.get("context", {}), context
        ):
            warnings.append(
                f"Known failure ({failure['count']}x): {failure['signature']}"
            )

    # Check preconditions
    for precond in profile.get("preconditions", []):
        if precond["reinforced"] >= 2:
            warnings.append(f"Precondition: {precond['text']}")

    # Low success rate warning
    rate = get_success_rate(profile)
    if (
        rate < 0.5
        and (profile.get("success_count", 0) + profile.get("failure_count", 0)) >= 5
    ):
        warnings.append(
            f"Low success rate: {rate:.0%} ({profile['failure_count']} failures)"
        )

    return warnings


# ── Internal helpers ──


def _add_outcome(profile, success):
    """Add outcome to rolling window."""
    outcomes = profile.setdefault("recent_outcomes", [])
    outcomes.append({"success": success, "ts": time.time()})
    if len(outcomes) > RATE_WINDOW:
        profile["recent_outcomes"] = outcomes[-RATE_WINDOW:]


def _extract_error_signature(error_text):
    """Extract a short, hashable error signature from error text."""
    if not error_text or not isinstance(error_text, str):
        return None
    # Take first non-empty line that looks like an error
    for line in error_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Common error prefixes
        for prefix in (
            "Error:",
            "error:",
            "BLOCKED:",
            "FAILED",
            "fatal:",
            "Traceback",
            "Permission denied",
            "No such file",
            "command not found",
            "[GATE",
        ):
            if prefix in line:
                # Truncate to 120 chars for storage
                return line[:120]
    # Fallback: first non-empty line, truncated
    first_line = error_text.strip().split("\n")[0].strip()
    if first_line and len(first_line) > 10:
        return first_line[:120]
    return None


def _extract_failure_context(tool_name, tool_input):
    """Extract contextual info from tool input for pattern matching."""
    context = {"tool": tool_name}
    if tool_name in ("Edit", "Write", "Read", "NotebookEdit"):
        fp = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if fp:
            context["extension"] = os.path.splitext(fp)[1]
            context["basename"] = os.path.basename(fp)
            # Sensitive path markers
            for marker in (".env", ".ssh", "credentials", "secret", "token"):
                if marker in fp.lower():
                    context["sensitive"] = True
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd:
            context["command_prefix"] = cmd.split()[0] if cmd.split() else ""
    elif tool_name == "Agent":
        context["subagent_type"] = tool_input.get("subagent_type", "")
    return context


def _context_matches(stored_context, current_context):
    """Check if current context matches a stored failure context."""
    if not stored_context:
        return False
    # Match on extension or basename or command_prefix
    for key in (
        "extension",
        "basename",
        "command_prefix",
        "sensitive",
        "subagent_type",
    ):
        if key in stored_context and key in current_context:
            if stored_context[key] == current_context[key]:
                return True
    return False


def _update_common_errors(profile, error_sig):
    """Track most common error patterns."""
    common = profile.setdefault("common_errors", [])
    for entry in common:
        if entry["pattern"] == error_sig:
            entry["count"] += 1
            entry["last_seen"] = time.time()
            return
    common.append({"pattern": error_sig, "count": 1, "last_seen": time.time()})
    if len(common) > MAX_COMMON_ERRORS:
        common.sort(key=lambda x: x["count"], reverse=True)
        profile["common_errors"] = common[:MAX_COMMON_ERRORS]
