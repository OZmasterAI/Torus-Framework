"""Domain mastery registry — manages per-domain knowledge, behavior, and gate overrides.

Domains are knowledge-area overlays (framework, web-dev, solana) that carry:
  - behavior.md: behavioral rules injected into every prompt when active
  - mastery.md: synthesized expertise injected at boot
  - profile.json: gate tuning, memory tags, L2 keywords, graduation state

Domains are orthogonal to modes (coding, debug, review). Both can be active simultaneously.
Modes = HOW you work. Domains = WHAT you know.

Directory layout:
  ~/.claude/domains/
    .active                     # plain text: active domain name
    framework/
      behavior.md
      mastery.md
      profile.json
"""

import fnmatch
import json
import os
from typing import Any, Dict, List, Optional, Tuple

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
DOMAINS_DIR = os.path.join(CLAUDE_DIR, "domains")
ACTIVE_FILE = os.path.join(DOMAINS_DIR, ".active")

# Default profile template for new domains
DEFAULT_PROFILE = {
    "description": "",
    "security_profile": "balanced",
    "gate_modes": {},
    "disabled_gates": [],
    "memory_tags": [],
    "l2_keywords": [],
    "auto_detect": {
        "live_state_project": [],
        "live_state_feature": [],
    },
    "graduation": {
        "graduated": False,
        "graduated_at": None,
        "memory_count_at_graduation": 0,
        "last_refreshed": None,
        "l2_scanned_until": None,
    },
    "token_budget": 800,
}


def list_domains() -> List[Dict[str, Any]]:
    """List all domains with their status.

    Returns list of dicts: [{name, description, active, graduated, has_mastery}]
    """
    if not os.path.isdir(DOMAINS_DIR):
        return []

    active = get_active_domain()
    domains = []
    for entry in sorted(os.listdir(DOMAINS_DIR)):
        domain_dir = os.path.join(DOMAINS_DIR, entry)
        if not os.path.isdir(domain_dir) or entry.startswith("."):
            continue
        profile = load_domain_profile(entry)
        mastery_path = os.path.join(domain_dir, "mastery.md")
        has_mastery = os.path.isfile(mastery_path) and os.path.getsize(mastery_path) > 0
        domains.append({
            "name": entry,
            "description": profile.get("description", ""),
            "active": entry == active,
            "graduated": profile.get("graduation", {}).get("graduated", False),
            "has_mastery": has_mastery,
        })
    return domains


def get_active_domain() -> Optional[str]:
    """Read the currently active domain name from .active file."""
    try:
        with open(ACTIVE_FILE) as f:
            name = f.read().strip()
        if name and os.path.isdir(os.path.join(DOMAINS_DIR, name)):
            return name
    except (FileNotFoundError, OSError):
        pass
    return None


def set_active_domain(name: Optional[str]) -> bool:
    """Set the active domain. Pass None to deactivate.

    Returns True on success, False if domain doesn't exist.
    """
    os.makedirs(DOMAINS_DIR, exist_ok=True)
    if name is None:
        # Deactivate
        try:
            os.remove(ACTIVE_FILE)
        except FileNotFoundError:
            pass
        return True

    domain_dir = os.path.join(DOMAINS_DIR, name)
    if not os.path.isdir(domain_dir):
        return False

    tmp = ACTIVE_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(name)
    os.replace(tmp, ACTIVE_FILE)
    return True


def load_domain_profile(name: str) -> Dict[str, Any]:
    """Load a domain's profile.json, merging with defaults for missing keys."""
    profile_path = os.path.join(DOMAINS_DIR, name, "profile.json")
    try:
        with open(profile_path) as f:
            profile = json.load(f)
        # Merge with defaults for forward compatibility
        merged = dict(DEFAULT_PROFILE)
        merged.update(profile)
        # Deep-merge graduation sub-dict
        grad_defaults = DEFAULT_PROFILE["graduation"]
        grad = merged.get("graduation", {})
        for k, v in grad_defaults.items():
            if k not in grad:
                grad[k] = v
        merged["graduation"] = grad
        # Deep-merge auto_detect sub-dict
        ad_defaults = DEFAULT_PROFILE["auto_detect"]
        ad = merged.get("auto_detect", {})
        for k, v in ad_defaults.items():
            if k not in ad:
                ad[k] = v
        merged["auto_detect"] = ad
        return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(DEFAULT_PROFILE)


def save_domain_profile(name: str, profile: Dict[str, Any]) -> None:
    """Save a domain's profile.json atomically."""
    profile_path = os.path.join(DOMAINS_DIR, name, "profile.json")
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    tmp = profile_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(profile, f, indent=2)
    os.replace(tmp, profile_path)


def load_domain_mastery(name: str) -> str:
    """Load a domain's mastery.md content. Returns empty string if missing."""
    mastery_path = os.path.join(DOMAINS_DIR, name, "mastery.md")
    try:
        with open(mastery_path) as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ""


def load_domain_behavior(name: str) -> str:
    """Load a domain's behavior.md content. Returns empty string if missing."""
    behavior_path = os.path.join(DOMAINS_DIR, name, "behavior.md")
    try:
        with open(behavior_path) as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ""


def detect_domain_from_live_state(live_state: Dict[str, Any]) -> Optional[str]:
    """Auto-detect domain from LIVE_STATE.json fields.

    Checks each domain's auto_detect patterns against:
      - live_state_project: fnmatch against project name
      - live_state_feature: fnmatch against feature name

    Returns the first matching domain name, or None.
    """
    if not live_state or not os.path.isdir(DOMAINS_DIR):
        return None

    project = live_state.get("project", "") or ""
    feature = live_state.get("feature", "") or ""

    for entry in sorted(os.listdir(DOMAINS_DIR)):
        domain_dir = os.path.join(DOMAINS_DIR, entry)
        if not os.path.isdir(domain_dir) or entry.startswith("."):
            continue
        profile = load_domain_profile(entry)
        auto_detect = profile.get("auto_detect", {})

        # Check project patterns
        for pattern in auto_detect.get("live_state_project", []):
            if project and fnmatch.fnmatch(project.lower(), pattern.lower()):
                return entry

        # Check feature patterns
        for pattern in auto_detect.get("live_state_feature", []):
            if feature and fnmatch.fnmatch(feature.lower(), pattern.lower()):
                return entry

    return None


def get_effective_gate_mode(gate_name: str, state: Dict[str, Any]) -> str:
    """Get the effective gate mode considering domain overrides.

    Priority: domain profile.json > security_profiles.py > "block" (default)
    Tier 1 gates (01/02/03) are always immune to downgrades.

    Args:
        gate_name: Gate identifier (short or full, e.g. "gate_04" or "gate_04_memory_first")
        state: Session state dict

    Returns:
        "block", "warn", or "disabled"
    """
    # Import here to avoid circular dependency
    from shared.security_profiles import get_gate_mode_for_profile

    # Check domain override first
    active = get_active_domain()
    if active:
        profile = load_domain_profile(active)

        # Check disabled_gates
        disabled = profile.get("disabled_gates", [])
        if _gate_matches_list(gate_name, disabled):
            return "disabled"

        # Check gate_modes
        gate_modes = profile.get("gate_modes", {})
        domain_mode = _lookup_gate_mode(gate_name, gate_modes)
        if domain_mode is not None:
            return domain_mode

    # Fall back to security profile
    return get_gate_mode_for_profile(gate_name, state)


def get_domain_memory_tags(name: str) -> List[str]:
    """Get the memory tags configured for a domain."""
    profile = load_domain_profile(name)
    return profile.get("memory_tags", [])


def get_domain_l2_keywords(name: str) -> List[str]:
    """Get the L2 (terminal history) search keywords for a domain."""
    profile = load_domain_profile(name)
    return profile.get("l2_keywords", [])


def get_domain_token_budget(name: str) -> int:
    """Get the token budget for domain knowledge injection."""
    profile = load_domain_profile(name)
    return profile.get("token_budget", 800)


def get_domain_context_for_injection(name: Optional[str] = None) -> Tuple[str, str]:
    """Get domain mastery and behavior for context injection.

    Args:
        name: Domain name, or None to use active domain.

    Returns:
        (mastery_text, behavior_text) tuple. Either may be empty string.
        mastery_text is truncated to the domain's token_budget (~4 chars/token).
    """
    if name is None:
        name = get_active_domain()
    if not name:
        return ("", "")

    mastery = load_domain_mastery(name)
    behavior = load_domain_behavior(name)

    # Truncate mastery to token budget
    budget = get_domain_token_budget(name)
    char_limit = budget * 4  # ~4 chars per token
    if len(mastery) > char_limit:
        mastery = mastery[:char_limit] + "\n[...truncated to token budget...]"

    return (mastery, behavior)


# ── Internal helpers ─────────────────────────────────────────────────

def _short_gate_name(name: str) -> str:
    """Extract short gate name (e.g. 'gate_04' from 'gate_04_memory_first')."""
    if name.startswith("gates."):
        name = name[len("gates."):]
    parts = name.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[1]}"
    return name


def _gate_matches_list(gate_name: str, names: list) -> bool:
    """Return True if gate_name matches any name in the list."""
    short = _short_gate_name(gate_name)
    for candidate in names:
        if _short_gate_name(candidate) == short:
            return True
    return False


def _lookup_gate_mode(gate_name: str, gate_modes: Dict[str, str]) -> Optional[str]:
    """Look up a gate's mode from a gate_modes dict.

    Tries exact match, then short-name match. Returns None if not found.
    """
    if gate_name in gate_modes:
        return gate_modes[gate_name]

    short = _short_gate_name(gate_name)
    for key, mode in gate_modes.items():
        if _short_gate_name(key) == short:
            return mode

    return None
