"""Security profile management for the Torus gate enforcement system.

Provides configurable risk profiles that gates can query to adjust their
behavior based on the active security posture: strict, balanced, or permissive.

Usage:
    from shared.security_profiles import get_profile, get_profile_config
    from shared.security_profiles import should_skip_for_profile, get_gate_mode_for_profile

    profile_name = get_profile(state)          # "strict" | "balanced" | "permissive"
    config = get_profile_config(state)         # full profile config dict
    skip = should_skip_for_profile("gate_14", state)  # True if gate disabled
    mode = get_gate_mode_for_profile("gate_05", state) # "block" | "warn" | "disabled"
"""

from typing import Dict, Any

# ── Profile Definitions ──────────────────────────────────────────────────────
# Each profile defines per-gate behavior overrides.
# Gate modes: "block" (default), "warn" (advisory only), "disabled" (skip entirely)
#
# Strict:     All gates active, max sensitivity. Suitable for production or
#             high-risk work. No gate downgrades.
# Balanced:   Default. Standard gate behavior -- some gates warn, most block.
# Permissive: Reduced friction for exploratory sessions. gate_14 disabled;
#             gate_05 downgraded to warn instead of block.

PROFILES: Dict[str, Dict[str, Any]] = {
    "strict": {
        "description": "All gates active with maximum sensitivity. No downgrades.",
        "gate_modes": {},  # Empty = all gates use their default block behavior
        "disabled_gates": [],
    },
    "balanced": {
        "description": "Standard behavior. Default profile for most sessions.",
        "gate_modes": {},  # Empty = all gates use their default block behavior
        "disabled_gates": [],
    },
    "permissive": {
        "description": "Reduced friction for exploratory work. Non-tier-1 gates advisory only.",
        "gate_modes": {
            "gate_04_memory_first": "warn",
            "gate_05_proof_before_fixed": "warn",
            "gate_06_save_fix": "warn",
            "gate_07_critical_file_guard": "warn",
            "gate_09_strategy_ban": "warn",
            "gate_10_model_enforcement": "warn",
            "gate_11_rate_limit": "warn",
            "gate_13_workspace_isolation": "warn",
            "gate_15_causal_chain": "warn",
            "gate_16_code_quality": "warn",
            "gate_17_injection_defense": "warn",
        },
        "disabled_gates": [
            "gate_14_confidence_check",
        ],
    },
    "refactor": {
        "description": "Reduced friction for mechanical bulk refactoring. Relaxes memory/save gates, keeps safety and quality gates active.",
        "gate_modes": {
            "gate_04_memory_first": "warn",
            "gate_06_save_fix": "warn",
            "gate_10_model_enforcement": "warn",
        },
        "disabled_gates": [
            "gate_14_confidence_check",
        ],
    },
}

# Valid profile names
VALID_PROFILES = set(PROFILES.keys())

# Default profile when none is set
DEFAULT_PROFILE = "balanced"


def get_profile(state: Dict[str, Any]) -> str:
    """Return the active security profile name from state.

    Reads 'security_profile' from the session state. Falls back to
    DEFAULT_PROFILE ("balanced") if the field is missing or invalid.

    Args:
        state: Session state dict (from load_state()).

    Returns:
        Profile name string: "strict", "balanced", or "permissive".
    """
    profile = state.get("security_profile", DEFAULT_PROFILE)
    if profile not in VALID_PROFILES:
        return DEFAULT_PROFILE
    return profile


def get_profile_config(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the full configuration dict for the active security profile.

    Args:
        state: Session state dict (from load_state()).

    Returns:
        Profile config dict with keys: description, gate_modes, disabled_gates.
    """
    profile_name = get_profile(state)
    return PROFILES[profile_name]


def should_skip_for_profile(gate_name: str, state: Dict[str, Any]) -> bool:
    """Return True if the active profile disables the given gate entirely.

    Gate names can be short (e.g. "gate_14") or long
    (e.g. "gate_14_confidence_check"). Both forms are matched.

    Args:
        gate_name: Gate identifier string (short or full name).
        state:     Session state dict (from load_state()).

    Returns:
        True if gate should be skipped, False otherwise.
    """
    config = get_profile_config(state)
    disabled = config.get("disabled_gates", [])
    return _matches_any(gate_name, disabled)


def get_gate_mode_for_profile(gate_name: str, state: Dict[str, Any]) -> str:
    """Return the enforcement mode for a gate under the active profile.

    Args:
        gate_name: Gate identifier string (short or full name).
        state:     Session state dict (from load_state()).

    Returns:
        "block"    -- Gate blocks tool calls as normal (default).
        "warn"     -- Gate emits advisory warnings but does not block.
        "disabled" -- Gate is skipped entirely (equivalent to should_skip).
    """
    # Check disabled list first
    if should_skip_for_profile(gate_name, state):
        return "disabled"

    config = get_profile_config(state)
    gate_modes = config.get("gate_modes", {})

    # Try exact key match first, then prefix match
    if gate_name in gate_modes:
        return gate_modes[gate_name]

    for key, mode in gate_modes.items():
        if _names_match(gate_name, key):
            return mode

    return "block"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _names_match(name_a: str, name_b: str) -> bool:
    """Return True if two gate name strings refer to the same gate.

    Handles short names ("gate_14") vs full names ("gate_14_confidence_check").
    Comparison is prefix-based on the canonical short form (first two segments).
    """
    short_a = _short_name(name_a)
    short_b = _short_name(name_b)
    return short_a == short_b


def _short_name(name: str) -> str:
    """Return the canonical short gate name (e.g. 'gate_14' from any variant)."""
    # Strip 'gates.' module prefix if present
    if name.startswith("gates."):
        name = name[len("gates."):]
    # Take first two underscore-delimited segments: "gate" + "NN"
    parts = name.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[1]}"
    return name


def _matches_any(gate_name: str, names: list) -> bool:
    """Return True if gate_name matches any name in the list."""
    for candidate in names:
        if _names_match(gate_name, candidate):
            return True
    return False
