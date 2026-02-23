"""Framework config validator for the Torus framework.

Validates key configuration files and structural invariants:
- settings.json: hooks structure, valid event types, command paths exist
- LIVE_STATE.json: required fields present with correct types
- Gate modules: all gates referenced in enforcer.py exist as files
- Skills: each skill directory has a SKILL.md file

Public API
----------
validate_settings(path=None) -> list[str]
    Returns a list of validation error strings (empty = valid).

validate_live_state(path=None) -> list[str]
    Returns a list of validation error strings (empty = valid).

validate_gates(enforcer_path=None) -> list[str]
    Returns a list of validation error strings (empty = valid).

validate_skills(skills_dir=None) -> list[str]
    Returns a list of validation error strings (empty = valid).

validate_all(base_dir=None) -> dict[str, list[str]]
    Runs all validators. Keys: "settings", "live_state", "gates", "skills".
    Values: lists of error strings (empty list = that validator passed).
"""

import json
import os
import re

# ── Defaults ────────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
_CLAUDE_DIR = os.path.join(_HOME, ".claude")
_HOOKS_DIR = os.path.join(_CLAUDE_DIR, "hooks")

_DEFAULT_SETTINGS_PATH = os.path.join(_CLAUDE_DIR, "settings.json")
_DEFAULT_LIVE_STATE_PATH = os.path.join(_CLAUDE_DIR, "LIVE_STATE.json")
_DEFAULT_ENFORCER_PATH = os.path.join(_HOOKS_DIR, "enforcer.py")
_DEFAULT_SKILLS_DIR = os.path.join(_CLAUDE_DIR, "skills")

# Valid Claude Code hook event types
_VALID_EVENT_TYPES = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PermissionRequest",
    "SubagentStart",
    "SubagentStop",
    "TaskCompleted",
    "PreCompact",
    "Stop",
    "Notification",
    "TeammateIdle",
}

# Required fields in LIVE_STATE.json and their expected Python types
_LIVE_STATE_REQUIRED = {
    "session_count": int,
    "project": str,
    "feature": str,
    "framework_version": str,
    "what_was_done": str,
    "next_steps": list,
    "known_issues": list,
}


# ── validate_settings ────────────────────────────────────────────────────────

def validate_settings(path=None):
    """Validate settings.json.

    Checks:
    - File exists and is valid JSON
    - Top-level "hooks" key is present and is a dict
    - Each event type key is a known Claude Code event
    - Each hook entry has a "type" and "command" field
    - Command paths that reference .py files resolve to existing files
      ($HOME and $CLAUDE_HOME are expanded)

    Returns a list of error strings. Empty list means valid.
    """
    errors = []
    fpath = path or _DEFAULT_SETTINGS_PATH

    if not os.path.exists(fpath):
        return [f"settings.json not found: {fpath}"]

    try:
        with open(fpath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"settings.json is not valid JSON: {e}"]
    except OSError as e:
        return [f"settings.json could not be read: {e}"]

    if not isinstance(data, dict):
        return ["settings.json root must be a JSON object"]

    hooks = data.get("hooks")
    if hooks is None:
        errors.append("settings.json: missing top-level 'hooks' key")
        return errors

    if not isinstance(hooks, dict):
        errors.append("settings.json: 'hooks' must be an object")
        return errors

    for event_type, entries in hooks.items():
        if event_type not in _VALID_EVENT_TYPES:
            errors.append(
                f"settings.json: unknown event type '{event_type}' "
                f"(valid: {sorted(_VALID_EVENT_TYPES)})"
            )

        if not isinstance(entries, list):
            errors.append(
                f"settings.json: hooks['{event_type}'] must be an array"
            )
            continue

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(
                    f"settings.json: hooks['{event_type}'][{i}] must be an object"
                )
                continue

            hook_list = entry.get("hooks", [])
            if not isinstance(hook_list, list):
                errors.append(
                    f"settings.json: hooks['{event_type}'][{i}].hooks must be an array"
                )
                continue

            for j, hook in enumerate(hook_list):
                if not isinstance(hook, dict):
                    errors.append(
                        f"settings.json: hooks['{event_type}'][{i}].hooks[{j}] must be an object"
                    )
                    continue

                if "type" not in hook:
                    errors.append(
                        f"settings.json: hooks['{event_type}'][{i}].hooks[{j}] missing 'type'"
                    )

                cmd = hook.get("command", "")
                if not cmd:
                    errors.append(
                        f"settings.json: hooks['{event_type}'][{i}].hooks[{j}] missing 'command'"
                    )
                    continue

                # Resolve $HOME / $CLAUDE_HOME in command paths and check .py files exist
                resolved_cmd = cmd.replace("$HOME", _HOME)
                # Extract quoted path arguments that end in .py
                py_paths = re.findall(r'"([^"]+\.py)"', resolved_cmd)
                for py_path in py_paths:
                    if not os.path.exists(py_path):
                        errors.append(
                            f"settings.json: command references missing file: {py_path} "
                            f"(event={event_type})"
                        )

    return errors


# ── validate_live_state ──────────────────────────────────────────────────────

def validate_live_state(path=None):
    """Validate LIVE_STATE.json.

    Checks:
    - File exists and is valid JSON
    - All required fields are present
    - Each required field has the correct type

    Returns a list of error strings. Empty list means valid.
    """
    errors = []
    fpath = path or _DEFAULT_LIVE_STATE_PATH

    if not os.path.exists(fpath):
        return [f"LIVE_STATE.json not found: {fpath}"]

    try:
        with open(fpath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"LIVE_STATE.json is not valid JSON: {e}"]
    except OSError as e:
        return [f"LIVE_STATE.json could not be read: {e}"]

    if not isinstance(data, dict):
        return ["LIVE_STATE.json root must be a JSON object"]

    for field, expected_type in _LIVE_STATE_REQUIRED.items():
        if field not in data:
            errors.append(f"LIVE_STATE.json: missing required field '{field}'")
            continue

        value = data[field]
        if not isinstance(value, expected_type):
            actual = type(value).__name__
            errors.append(
                f"LIVE_STATE.json: field '{field}' expected {expected_type.__name__}, "
                f"got {actual}"
            )

    return errors


# ── validate_gates ───────────────────────────────────────────────────────────

def validate_gates(enforcer_path=None):
    """Validate that all gate modules in the canonical registry exist as files.

    Imports GATE_MODULES from shared.gate_registry (single source of truth)
    and checks that each module (e.g. "gates.gate_01_read_before_edit") has
    a corresponding .py file in the hooks/gates/ directory.

    Returns a list of error strings. Empty list means valid.
    """
    from shared.gate_registry import GATE_MODULES

    errors = []
    hooks_dir = os.path.dirname(enforcer_path or _DEFAULT_ENFORCER_PATH)

    for module in GATE_MODULES:
        parts = module.split(".")
        if len(parts) != 2:
            errors.append(f"gate_registry: unexpected module format '{module}'")
            continue

        subdir, modname = parts
        expected_path = os.path.join(hooks_dir, subdir, modname + ".py")
        if not os.path.exists(expected_path):
            errors.append(
                f"gate_registry: gate module '{module}' references missing file: "
                f"{expected_path}"
            )

    return errors


# ── validate_skills ──────────────────────────────────────────────────────────

def validate_skills(skills_dir=None):
    """Validate that every skill directory contains a SKILL.md file.

    Returns a list of error strings. Empty list means valid.
    """
    errors = []
    sdir = skills_dir or _DEFAULT_SKILLS_DIR

    if not os.path.exists(sdir):
        return [f"skills directory not found: {sdir}"]

    if not os.path.isdir(sdir):
        return [f"skills path is not a directory: {sdir}"]

    try:
        entries = sorted(os.listdir(sdir))
    except OSError as e:
        return [f"skills directory could not be read: {e}"]

    found_skills = 0
    for entry in entries:
        entry_path = os.path.join(sdir, entry)
        if not os.path.isdir(entry_path):
            continue  # Skip non-directory files (e.g. __init__.py)
        found_skills += 1
        skill_md = os.path.join(entry_path, "SKILL.md")
        if not os.path.exists(skill_md):
            errors.append(
                f"skill '{entry}': missing SKILL.md at {skill_md}"
            )

    if found_skills == 0:
        errors.append(f"skills directory contains no skill subdirectories: {sdir}")

    return errors


# ── validate_all ─────────────────────────────────────────────────────────────

def validate_all(base_dir=None):
    """Run all validators and return a summary dict.

    Args:
        base_dir: Optional override for the base .claude directory.
                  If provided, all default paths are derived from it.

    Returns:
        dict with keys "settings", "live_state", "gates", "skills".
        Each value is a list of error strings (empty = that validator passed).
    """
    if base_dir is not None:
        settings_path = os.path.join(base_dir, "settings.json")
        live_state_path = os.path.join(base_dir, "LIVE_STATE.json")
        enforcer_path = os.path.join(base_dir, "hooks", "enforcer.py")
        skills_dir = os.path.join(base_dir, "skills")
    else:
        settings_path = None
        live_state_path = None
        enforcer_path = None
        skills_dir = None

    return {
        "settings": validate_settings(settings_path),
        "live_state": validate_live_state(live_state_path),
        "gates": validate_gates(enforcer_path),
        "skills": validate_skills(skills_dir),
    }
