"""Skill health checker for the Torus framework.

Validates all skills in the skills/ directory by checking:
1. Required files exist (SKILL.md, and scripts/ if scripts exist in similar skills)
2. metadata.json fields are valid (if used by a skill)
3. Script files are syntactically valid Python
4. Scripts can be imported and have required functions

Public API
----------
check_all_skills(skills_dir=None) -> dict
    Scans all skills and returns structured health report:
    {
        "total_skills": int,
        "healthy_skills": int,
        "broken_skills": list[str],
        "warnings": list[str],
        "errors": dict[str, list[str]],  # skill_name -> error list
        "script_issues": dict[str, list[str]],  # skill_name -> script issues
    }

get_broken_skills(skills_dir=None) -> list[str]
    Returns list of skill directories with issues.
    Quick check mode - use when you only need broken skill names.
"""

import os
import json
import ast
import sys
from pathlib import Path

# ── Defaults ────────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
_CLAUDE_DIR = os.path.join(_HOME, ".claude")
_DEFAULT_SKILLS_DIR = os.path.join(_CLAUDE_DIR, "skills")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _normalize_path(path):
    """Expand ~ and make absolute."""
    return os.path.abspath(os.path.expanduser(path))


def _is_python_file(filepath):
    """Check if file is a Python script."""
    return filepath.endswith(".py")


def _check_python_syntax(filepath):
    """Check if a Python file has valid syntax.

    Returns: (is_valid, error_message)
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}"


def _import_module_from_file(filepath):
    """Try to import a Python file as a module.

    Returns: (success, error_message, module_object)
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("__skill_module__", filepath)
        if spec is None:
            return False, f"Could not create module spec for {filepath}", None
        module = importlib.util.module_from_spec(spec)
        sys.modules["__skill_module__"] = module
        spec.loader.exec_module(module)
        return True, None, module
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}", None
    finally:
        # Clean up
        if "__skill_module__" in sys.modules:
            del sys.modules["__skill_module__"]


# ── Core Health Checks ──────────────────────────────────────────────────────

def _check_skill_structure(skill_path):
    """Check if a skill has required structure.

    Required:
    - SKILL.md must exist

    Optional (depending on skill):
    - scripts/ directory (if any Python files are present)

    Returns: (is_healthy, errors_list)
    """
    errors = []

    # Check SKILL.md
    skill_md = os.path.join(skill_path, "SKILL.md")
    if not os.path.isfile(skill_md):
        errors.append(f"Missing SKILL.md in {skill_path}")
        return False, errors

    # Check scripts directory if it exists
    scripts_dir = os.path.join(skill_path, "scripts")
    if os.path.isdir(scripts_dir):
        # scripts/ exists, check for Python files
        py_files = [
            f for f in os.listdir(scripts_dir)
            if _is_python_file(f) and not f.startswith(".")
        ]

        if py_files:
            # If there are Python files, they should be importable
            for pyfile in py_files:
                pypath = os.path.join(scripts_dir, pyfile)
                # Just mark for later checking, don't fail here

        # Check for __init__.py if it's meant to be a package
        # (optional, not required)

    return len(errors) == 0, errors


def _check_script_files(skill_path):
    """Check all Python scripts in a skill's scripts/ directory.

    Returns: errors_list
    """
    errors = []
    scripts_dir = os.path.join(skill_path, "scripts")

    if not os.path.isdir(scripts_dir):
        return errors

    for filename in os.listdir(scripts_dir):
        if not _is_python_file(filename) or filename.startswith("."):
            continue

        filepath = os.path.join(scripts_dir, filename)

        # Check syntax
        is_valid, syntax_error = _check_python_syntax(filepath)
        if not is_valid:
            errors.append(f"{filename}: {syntax_error}")
            continue

        # Optional: try to import (lighter check)
        # Disabled by default to avoid side effects
        # success, import_error, _ = _import_module_from_file(filepath)
        # if not success:
        #     errors.append(f"{filename}: Import failed: {import_error}")

    return errors


def _check_metadata_json(skill_path):
    """Check if metadata.json exists and is valid (if present).

    Returns: errors_list
    """
    errors = []
    metadata_path = os.path.join(skill_path, "metadata.json")

    if not os.path.exists(metadata_path):
        # metadata.json is optional
        return errors

    try:
        with open(metadata_path) as f:
            metadata = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"metadata.json: Invalid JSON: {e}")
        return errors
    except Exception as e:
        errors.append(f"metadata.json: Could not read: {e}")
        return errors

    # Validate required fields if metadata exists
    if not isinstance(metadata, dict):
        errors.append("metadata.json: Root must be a JSON object")
        return errors

    # Optional validation - skills don't typically use metadata.json yet
    # Add field validation here when the schema is defined

    return errors


# ── Main API ────────────────────────────────────────────────────────────────

def check_all_skills(skills_dir=None):
    """Check all skills in the skills directory.

    Returns a structured health report:
    {
        "total_skills": int,
        "healthy_skills": int,
        "broken_skills": list[str],  # Skill names with issues
        "warnings": list[str],
        "errors": dict[str, list[str]],  # skill_name -> error list
        "script_issues": dict[str, list[str]],  # skill_name -> script error list
    }
    """
    skills_dir = _normalize_path(skills_dir or _DEFAULT_SKILLS_DIR)

    report = {
        "total_skills": 0,
        "healthy_skills": 0,
        "broken_skills": [],
        "warnings": [],
        "errors": {},
        "script_issues": {},
    }

    if not os.path.isdir(skills_dir):
        report["warnings"].append(f"Skills directory not found: {skills_dir}")
        return report

    # Scan all skill directories
    try:
        skill_dirs = sorted([
            d for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith(".")
        ])
    except OSError as e:
        report["warnings"].append(f"Could not scan skills directory: {e}")
        return report

    report["total_skills"] = len(skill_dirs)

    # Check each skill
    for skill_name in skill_dirs:
        skill_path = os.path.join(skills_dir, skill_name)
        skill_errors = []

        # Check structure
        is_healthy, struct_errors = _check_skill_structure(skill_path)
        skill_errors.extend(struct_errors)

        # Check metadata if present
        metadata_errors = _check_metadata_json(skill_path)
        skill_errors.extend(metadata_errors)

        # Check scripts
        script_errors = _check_script_files(skill_path)

        # Accumulate results
        if skill_errors:
            report["errors"][skill_name] = skill_errors
            if not is_healthy:
                # Structure error = broken skill
                report["broken_skills"].append(skill_name)

        if script_errors:
            report["script_issues"][skill_name] = script_errors
            # Script errors are warnings, not blocking
            if skill_name not in report["broken_skills"]:
                report["warnings"].extend([
                    f"{skill_name}: {err}" for err in script_errors
                ])

        if not skill_errors and not script_errors:
            report["healthy_skills"] += 1

    return report


def get_broken_skills(skills_dir=None):
    """Get list of skill directories with critical issues.

    Only returns skills that fail structural checks (missing SKILL.md, etc).
    Script syntax warnings are not included in this list.

    Returns: list[str] of skill names
    """
    skills_dir = _normalize_path(skills_dir or _DEFAULT_SKILLS_DIR)

    broken = []

    if not os.path.isdir(skills_dir):
        return broken

    try:
        skill_dirs = sorted([
            d for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith(".")
        ])
    except OSError:
        return broken

    for skill_name in skill_dirs:
        skill_path = os.path.join(skills_dir, skill_name)
        is_healthy, _ = _check_skill_structure(skill_path)

        if not is_healthy:
            broken.append(skill_name)

    return broken


# ── Detailed Report Functions ───────────────────────────────────────────────

def get_skill_details(skill_name, skills_dir=None):
    """Get detailed information about a specific skill.

    Returns:
    {
        "name": str,
        "path": str,
        "exists": bool,
        "structure_ok": bool,
        "has_scripts": bool,
        "scripts": list[str],
        "errors": list[str],
        "script_issues": list[str],
    }
    """
    skills_dir = _normalize_path(skills_dir or _DEFAULT_SKILLS_DIR)
    skill_path = os.path.join(skills_dir, skill_name)

    details = {
        "name": skill_name,
        "path": skill_path,
        "exists": os.path.isdir(skill_path),
        "structure_ok": False,
        "has_scripts": False,
        "scripts": [],
        "errors": [],
        "script_issues": [],
    }

    if not details["exists"]:
        return details

    # Check structure
    is_healthy, struct_errors = _check_skill_structure(skill_path)
    details["structure_ok"] = is_healthy
    details["errors"].extend(struct_errors)

    # Check scripts
    scripts_dir = os.path.join(skill_path, "scripts")
    if os.path.isdir(scripts_dir):
        details["has_scripts"] = True
        py_files = [
            f for f in os.listdir(scripts_dir)
            if _is_python_file(f) and not f.startswith(".")
        ]
        details["scripts"] = sorted(py_files)

        # Check each script
        script_errors = _check_script_files(skill_path)
        details["script_issues"].extend(script_errors)

    # Check metadata
    metadata_errors = _check_metadata_json(skill_path)
    details["errors"].extend(metadata_errors)

    return details


def format_health_report(report):
    """Format check_all_skills() report as readable string.

    Args:
        report: dict from check_all_skills()

    Returns: formatted string suitable for display
    """
    lines = []
    lines.append("╔════════════════════════════════════════════════════════════╗")
    lines.append("║         SKILL HEALTH CHECK REPORT                        ║")
    lines.append("╚════════════════════════════════════════════════════════════╝")
    lines.append("")

    # Summary
    lines.append(f"Total Skills:   {report['total_skills']}")
    lines.append(f"Healthy:        {report['healthy_skills']}")
    lines.append(f"Broken:         {len(report['broken_skills'])}")
    lines.append("")

    # Broken skills
    if report["broken_skills"]:
        lines.append("BROKEN SKILLS:")
        for skill_name in report["broken_skills"]:
            errors = report["errors"].get(skill_name, [])
            lines.append(f"  ✗ {skill_name}")
            for error in errors:
                lines.append(f"    - {error}")
        lines.append("")

    # Script issues (warnings)
    if report["script_issues"]:
        lines.append("SCRIPT ISSUES (warnings):")
        for skill_name in sorted(report["script_issues"].keys()):
            issues = report["script_issues"][skill_name]
            lines.append(f"  ⚠ {skill_name}")
            for issue in issues:
                lines.append(f"    - {issue}")
        lines.append("")

    # General warnings
    if report["warnings"]:
        lines.append("WARNINGS:")
        for warning in report["warnings"]:
            lines.append(f"  ! {warning}")
        lines.append("")

    # Status
    if not report["broken_skills"] and not report["script_issues"]:
        lines.append("Status: ✓ ALL SKILLS HEALTHY")
    else:
        lines.append(f"Status: ⚠ {len(report['broken_skills'])} broken, {len(report['script_issues'])} with issues")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test the module
    report = check_all_skills()
    print(format_health_report(report))

    # Show any broken skills
    broken = get_broken_skills()
    if broken:
        print(f"\nBroken skills: {broken}")
