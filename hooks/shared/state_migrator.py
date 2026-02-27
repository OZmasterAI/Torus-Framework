"""State migration and validation utilities for schema evolution.

Provides tools to:
1. Migrate state objects by adding missing fields with defaults
2. Validate state structure and types
3. Show schema diffs for debugging and documentation

Used by gates and boot.py for state validation and versioning.
"""

import json
import logging

from shared.state import (
    default_state,
    get_state_schema,
    STATE_VERSION,
    MAX_FILES_READ,
    MAX_VERIFIED_FIXES,
    MAX_PENDING_VERIFICATION,
    MAX_UNLOGGED_ERRORS,
    MAX_ERROR_PATTERNS,
    MAX_ACTIVE_BANS,
    MAX_PENDING_CHAINS,
    MAX_EDIT_STREAK,
    MAX_GATE_BLOCK_OUTCOMES,
)
from shared.security_profiles import VALID_PROFILES

logger = logging.getLogger(__name__)


def migrate_state(state_dict):
    """Migrate a state object by adding missing fields with defaults.

    Iterates over the schema from get_state_schema() and default_state(),
    adding any missing fields to the state_dict with their default values.

    Args:
        state_dict (dict): The state object to migrate.

    Returns:
        dict: The migrated state with all expected fields present.

    Example:
        >>> state = {"_version": 2, "files_read": []}
        >>> migrated = migrate_state(state)
        >>> "skill_usage" in migrated  # True (added from defaults)
    """
    if not isinstance(state_dict, dict):
        logger.warning("migrate_state called with non-dict: %s", type(state_dict))
        return default_state()

    defaults = default_state()
    migrated = state_dict.copy()

    for field, default_value in defaults.items():
        if field not in migrated:
            migrated[field] = default_value
            logger.debug("migrate_state: added missing field %s with default", field)

    # Ensure version is correct
    migrated["_version"] = STATE_VERSION

    return migrated


def validate_state(state_dict):
    """Validate a state object's structure and types.

    Checks that:
    - state_dict is a dict
    - All required fields from schema are present
    - Field types match expected types (int, str, bool, list, dict, float)
    - List fields don't exceed their MAX_* caps
    - Dict fields exist and are dicts

    Args:
        state_dict (dict): The state object to validate.

    Returns:
        tuple: (is_valid: bool, errors: list of str, warnings: list of str)

    Example:
        >>> state = default_state()
        >>> is_valid, errors, warnings = validate_state(state)
        >>> is_valid  # True
        >>> len(errors)  # 0
    """
    errors = []
    warnings = []

    if not isinstance(state_dict, dict):
        errors.append(f"state_dict is not a dict: {type(state_dict)}")
        return False, errors, warnings

    schema = get_state_schema()
    defaults = default_state()

    # Map schema type strings to Python types
    type_map = {
        "int": int,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "float": float,
    }

    # Check each field in the schema
    for field_name, field_meta in schema.items():
        expected_type_str = field_meta.get("type", "unknown")
        expected_type = type_map.get(expected_type_str)

        # Check presence
        if field_name not in state_dict:
            errors.append(f"Missing required field: {field_name}")
            continue

        value = state_dict[field_name]

        # Special case: None is allowed for optional fields
        if value is None and field_name in ("recent_test_failure", "last_test_exit_code"):
            continue

        # Type check (int is acceptable where float is expected — every int is a valid float)
        if expected_type is not None and not isinstance(value, expected_type):
            if expected_type is float and isinstance(value, int):
                pass  # int is a valid numeric value for float fields (e.g., timestamps)
            else:
                errors.append(
                    f"Field {field_name}: expected {expected_type_str}, got {type(value).__name__}"
                )
                continue

        # Size check for lists with MAX_* caps
        max_size = field_meta.get("max_size")
        if isinstance(value, list) and max_size is not None and len(value) > max_size:
            warnings.append(f"Field {field_name}: exceeds max_size {max_size} (has {len(value)})")

        # Additional checks for specific fields
        if field_name == "error_pattern_counts" and isinstance(value, dict):
            # Check that all keys are strings and values are ints
            for k, v in value.items():
                if not isinstance(k, str):
                    warnings.append(f"error_pattern_counts: key is not string: {k}")
                if not isinstance(v, int):
                    warnings.append(f"error_pattern_counts: value for {k} is not int")

        if field_name == "active_bans" and isinstance(value, dict):
            # Check that bans have the right structure
            for ban_id, ban_info in value.items():
                if not isinstance(ban_info, dict):
                    warnings.append(f"active_bans: entry {ban_id} is not a dict")
                    continue
                required_ban_keys = {"fail_count", "first_failed", "last_failed"}
                for req_key in required_ban_keys:
                    if req_key not in ban_info:
                        warnings.append(f"active_bans[{ban_id}]: missing key {req_key}")

        if field_name == "security_profile" and isinstance(value, str):
            # Check that security_profile is one of the valid values
            if value not in VALID_PROFILES:
                warnings.append(
                    f"security_profile: invalid value '{value}' (must be one of {VALID_PROFILES})"
                )

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def get_schema_diff(state_dict, expected_defaults=None):
    """Get a structured diff between state_dict and the schema defaults.

    Shows:
    - Missing fields (in defaults but not in state)
    - Extra fields (in state but not in defaults)
    - Type mismatches (field type doesn't match schema)
    - Value changes (field value differs from default)

    Args:
        state_dict (dict): The state object to analyze.
        expected_defaults (dict, optional): Override the default state.
                                           Defaults to default_state().

    Returns:
        dict: Diff report with structure:
            {
                "schema_version": int,
                "missing_fields": [{"name": str, "default": obj}],
                "extra_fields": [{"name": str, "value": obj}],
                "type_mismatches": [{"name": str, "expected": str, "actual": str}],
                "value_changes": [{"name": str, "default": obj, "current": obj}],
                "summary": {"missing": N, "extra": N, "type_mismatch": N, "changed": N},
            }

    Example:
        >>> state = {"_version": 3, "files_read": []}  # Missing many fields
        >>> diff = get_schema_diff(state)
        >>> len(diff["missing_fields"])  # Many
        >>> diff["summary"]["missing"]  # Same count
    """
    if expected_defaults is None:
        expected_defaults = default_state()

    if not isinstance(state_dict, dict):
        return {
            "schema_version": STATE_VERSION,
            "error": f"state_dict is not a dict: {type(state_dict)}",
            "missing_fields": [],
            "extra_fields": [],
            "type_mismatches": [],
            "value_changes": [],
            "summary": {"missing": 0, "extra": 0, "type_mismatch": 0, "changed": 0},
        }

    schema = get_state_schema()
    type_map = {
        "int": int,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "float": float,
    }

    missing_fields = []
    extra_fields = []
    type_mismatches = []
    value_changes = []

    # Find missing fields
    for field_name, default_value in expected_defaults.items():
        if field_name not in state_dict:
            missing_fields.append({"name": field_name, "default": _serialize_for_diff(default_value)})
        else:
            # Check type
            field_meta = schema.get(field_name, {})
            expected_type_str = field_meta.get("type", "unknown")
            expected_type = type_map.get(expected_type_str)
            actual_value = state_dict[field_name]

            # Special case: None is allowed for recent_test_failure
            if field_name == "recent_test_failure" and actual_value is None:
                continue

            if expected_type is not None and not isinstance(actual_value, expected_type):
                type_mismatches.append({
                    "name": field_name,
                    "expected": expected_type_str,
                    "actual": type(actual_value).__name__,
                })
            elif actual_value != default_value:
                # Value differs from default
                value_changes.append({
                    "name": field_name,
                    "default": _serialize_for_diff(default_value),
                    "current": _serialize_for_diff(actual_value),
                })

    # Find extra fields (shouldn't happen after migration, but check anyway)
    for field_name in state_dict:
        if field_name not in expected_defaults:
            extra_fields.append({
                "name": field_name,
                "value": _serialize_for_diff(state_dict[field_name]),
            })

    summary = {
        "missing": len(missing_fields),
        "extra": len(extra_fields),
        "type_mismatch": len(type_mismatches),
        "changed": len(value_changes),
    }

    return {
        "schema_version": STATE_VERSION,
        "missing_fields": missing_fields,
        "extra_fields": extra_fields,
        "type_mismatches": type_mismatches,
        "value_changes": value_changes,
        "summary": summary,
    }


def _serialize_for_diff(value):
    """Serialize a value for JSON-safe output in diffs.

    Handles special types that aren't JSON-serializable by default.
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    elif isinstance(value, list):
        # For long lists, show [count: N] instead of full list
        if len(value) > 5:
            return f"[list: {len(value)} items]"
        return value
    elif isinstance(value, dict):
        # For large dicts, show {count: N} instead of full dict
        if len(value) > 3:
            return f"{{dict: {len(value)} keys}}"
        return value
    else:
        return str(value)


def validate_and_migrate(state_dict):
    """Convenience function: migrate state and validate the result.

    Performs both migration and validation, logging any issues.

    Args:
        state_dict (dict): The state object to migrate and validate.

    Returns:
        tuple: (migrated_state: dict, is_valid: bool, errors: list, warnings: list)
    """
    migrated = migrate_state(state_dict)
    is_valid, errors, warnings = validate_state(migrated)

    if errors:
        logger.error("State validation errors: %s", "; ".join(errors))
    if warnings:
        logger.warning("State validation warnings: %s", "; ".join(warnings))

    return migrated, is_valid, errors, warnings


def get_schema_metadata():
    """Get the full schema metadata for API exposure.

    Returns a dict describing the state schema suitable for REST API
    responses (dashboard, state inspection tools, etc.).

    Returns:
        dict: {
            "version": int,
            "schema": {field_name: metadata_dict, ...},
            "field_count": int,
        }
    """
    schema = get_state_schema()
    return {
        "version": STATE_VERSION,
        "schema": schema,
        "field_count": len(schema),
    }
