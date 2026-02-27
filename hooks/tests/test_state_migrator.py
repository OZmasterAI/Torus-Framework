#!/usr/bin/env python3
"""Test suite for state_migrator.py"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.state_migrator import (
    migrate_state,
    validate_state,
    get_schema_diff,
    validate_and_migrate,
    get_schema_metadata
)
from shared.state import default_state

def test_migrate_state():
    """Test migrate_state() adds missing fields"""
    print("\n" + "=" * 60)
    print("TEST 1: migrate_state() - add missing fields")
    print("=" * 60)

    # Create a minimal state (missing many fields)
    minimal_state = {
        "_version": 3,
        "files_read": ["/tmp/test.py"],
        "tool_call_count": 5,
    }

    migrated = migrate_state(minimal_state)
    print(f"Input fields: {len(minimal_state)}")
    print(f"Output fields: {len(migrated)}")
    print(f"Has 'skill_usage' field: {'skill_usage' in migrated}")
    print(f"Has 'security_profile' field: {'security_profile' in migrated}")
    print(f"security_profile default value: {migrated['security_profile']}")

    assert "skill_usage" in migrated, "Missing 'skill_usage' field"
    assert "security_profile" in migrated, "Missing 'security_profile' field"
    assert migrated["security_profile"] == "balanced", "Wrong default value"
    print("PASSED")

def test_validate_state():
    """Test validate_state() type checking"""
    print("\n" + "=" * 60)
    print("TEST 2: validate_state() - type checking")
    print("=" * 60)

    # Test with good state
    good_state = default_state()
    is_valid, errors, warnings = validate_state(good_state)
    print(f"Default state is valid: {is_valid}")
    print(f"Errors: {errors}")
    print(f"Warnings: {len(warnings)} warnings")

    assert is_valid, f"Default state should be valid, got errors: {errors}"
    assert len(errors) == 0, f"Should have no errors, got: {errors}"
    print("Good state validation: PASSED")

    # Test with bad state
    bad_state = default_state()
    bad_state["files_read"] = "not a list"  # Wrong type
    is_valid, errors, warnings = validate_state(bad_state)
    print(f"\nBad state is valid: {is_valid}")
    print(f"Errors found: {len(errors)}")
    print(f"First error: {errors[0] if errors else 'None'}")

    assert not is_valid, "Bad state should be invalid"
    assert len(errors) > 0, "Should have detected type error"
    print("Bad state detection: PASSED")

def test_get_schema_diff():
    """Test get_schema_diff() shows missing fields"""
    print("\n" + "=" * 60)
    print("TEST 3: get_schema_diff() - show missing fields")
    print("=" * 60)

    # Minimal state again
    minimal = {"_version": 3, "files_read": []}
    diff = get_schema_diff(minimal)
    print(f"Schema version: {diff['schema_version']}")
    print(f"Missing fields: {diff['summary']['missing']}")
    print(f"Extra fields: {diff['summary']['extra']}")
    print(f"Type mismatches: {diff['summary']['type_mismatch']}")
    print(f"Changed values: {diff['summary']['changed']}")
    print(f"First 3 missing fields:")
    for field in diff['missing_fields'][:3]:
        print(f"  - {field['name']}")

    assert diff['summary']['missing'] > 0, "Should have missing fields"
    assert diff['summary']['extra'] == 0, "Should have no extra fields"
    print("PASSED")

def test_validate_and_migrate():
    """Test validate_and_migrate() combined operation"""
    print("\n" + "=" * 60)
    print("TEST 4: validate_and_migrate() - combined operation")
    print("=" * 60)

    minimal = {"_version": 2, "files_read": ["test.py"]}
    migrated, is_valid, errors, warnings = validate_and_migrate(minimal)
    print(f"Migrated successfully: {is_valid}")
    print(f"Final field count: {len(migrated)}")
    print(f"Has all expected fields: {len(migrated) == len(default_state())}")

    assert is_valid, f"Should be valid after migration, got errors: {errors}"
    assert len(migrated) == len(default_state()), "Should have all fields"
    print("PASSED")

def test_get_schema_metadata():
    """Test get_schema_metadata() API info"""
    print("\n" + "=" * 60)
    print("TEST 5: get_schema_metadata() - API schema info")
    print("=" * 60)

    metadata = get_schema_metadata()
    print(f"State schema version: {metadata['version']}")
    print(f"Total fields in schema: {metadata['field_count']}")
    print(f"First 3 fields in schema:")
    for i, (name, meta) in enumerate(list(metadata['schema'].items())[:3]):
        desc = meta['description'][:50] if len(meta['description']) > 50 else meta['description']
        print(f"  - {name}: {meta['type']} ({desc}...)")

    assert metadata['field_count'] > 0, "Should have fields in schema"
    assert "version" in metadata, "Should have version key"
    assert "schema" in metadata, "Should have schema key"
    print("PASSED")

def test_security_profile_validation():
    """Test that security_profile is validated correctly"""
    print("\n" + "=" * 60)
    print("TEST 6: security_profile validation")
    print("=" * 60)

    # Valid profiles
    for profile in ["strict", "balanced", "permissive"]:
        state = default_state()
        state["security_profile"] = profile
        is_valid, errors, warnings = validate_state(state)
        print(f"Profile '{profile}': valid={is_valid}, errors={len(errors)}")
        assert is_valid, f"Profile {profile} should be valid"

    # Invalid profile
    state = default_state()
    state["security_profile"] = "invalid_profile"
    is_valid, errors, warnings = validate_state(state)
    print(f"Profile 'invalid_profile': valid={is_valid}, warnings={len(warnings)}")
    assert not is_valid or len(warnings) > 0, "Should warn on invalid profile"
    print("PASSED")

if __name__ == "__main__":
    try:
        test_migrate_state()
        test_validate_state()
        test_get_schema_diff()
        test_validate_and_migrate()
        test_get_schema_metadata()
        test_security_profile_validation()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
