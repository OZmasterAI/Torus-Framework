"""Patched version with fixed validation logic for testing"""

import json
import logging

from shared.state import (
    default_state,
    get_state_schema,
    STATE_VERSION,
)

logger = logging.getLogger(__name__)


def validate_state_fixed(state_dict):
    """Fixed validate_state with flexible numeric type checking."""
    errors = []
    warnings = []

    if not isinstance(state_dict, dict):
        errors.append(f"state_dict is not a dict: {type(state_dict)}")
        return False, errors, warnings

    schema = get_state_schema()

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

        # Special cases: None is allowed for optional fields
        if field_name in ("recent_test_failure", "last_test_exit_code") and value is None:
            continue

        # Type check with flexible numeric types
        # Timestamps can be int or float; floats are preferred but both work
        if expected_type_str == "float" and isinstance(value, (int, float)):
            pass  # Both int and float acceptable for numeric timestamps
        elif expected_type is not None and not isinstance(value, expected_type):
            errors.append(
                f"Field {field_name}: expected {expected_type_str}, got {type(value).__name__}"
            )
            continue

        # Size check for lists with MAX_* caps
        max_size = field_meta.get("max_size")
        if isinstance(value, list) and max_size is not None and len(value) > max_size:
            warnings.append(f"Field {field_name}: exceeds max_size {max_size} (has {len(value)})")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


if __name__ == "__main__":
    print("Testing fixed validation...")
    state = default_state()
    is_valid, errors, warnings = validate_state_fixed(state)
    print(f"Is valid: {is_valid}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    if errors:
        print(f"First error: {errors[0]}")
    print("Test completed.")
