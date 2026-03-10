#!/usr/bin/env python3
"""Tests for subproject detection via .claude-project marker."""

import json
import os
import tempfile

from tests.harness import test

from boot_pkg.util import (
    detect_project,
    scan_subproject_states,
    SUBPROJECT_MARKER,
    PROJECT_STATE_FILENAME,
    PROJECTS_DIR,
)

# Save original and create temp dir for isolated tests
_ORIG_PROJECTS_DIR = PROJECTS_DIR

print("\n--- Project Detection: Subproject Support ---")


def _with_temp_projects(fn):
    """Run fn(temp_projects_dir) with PROJECTS_DIR monkeypatched."""
    import boot_pkg.util as _util

    with tempfile.TemporaryDirectory() as tmpdir:
        proj_dir = os.path.join(tmpdir, "projects")
        os.makedirs(proj_dir)
        old = _util.PROJECTS_DIR
        _util.PROJECTS_DIR = proj_dir
        try:
            fn(proj_dir)
        finally:
            _util.PROJECTS_DIR = old


# Test 1: Non-project cwd returns 4-None tuple
def _test_non_project(projects_dir):
    result = detect_project("/tmp")
    test(
        "PD: non-project cwd returns 4-None tuple",
        result == (None, None, None, None),
        f"got {result}",
    )


_with_temp_projects(_test_non_project)


# Test 2: Project-level cwd returns project info with None subproject
def _test_project_level(projects_dir):
    proj = os.path.join(projects_dir, "myproj")
    os.makedirs(proj)
    result = detect_project(proj)
    test(
        "PD: project-level cwd returns (name, dir, None, None)",
        result == ("myproj", proj, None, None),
        f"got {result}",
    )


_with_temp_projects(_test_project_level)


# Test 3: Subproject detected when marker present
def _test_subproject_with_marker(projects_dir):
    proj = os.path.join(projects_dir, "myproj")
    sub = os.path.join(proj, "sub1")
    os.makedirs(sub)
    # Create marker
    open(os.path.join(sub, SUBPROJECT_MARKER), "w").close()
    result = detect_project(sub)
    test(
        "PD: subproject detected with .claude-project marker",
        result == ("myproj", proj, "sub1", sub),
        f"got {result}",
    )


_with_temp_projects(_test_subproject_with_marker)


# Test 4: No subproject when marker absent
def _test_subproject_without_marker(projects_dir):
    proj = os.path.join(projects_dir, "myproj")
    sub = os.path.join(proj, "sub1")
    os.makedirs(sub)
    # No marker file
    result = detect_project(sub)
    test(
        "PD: no subproject when marker absent",
        result == ("myproj", proj, None, None),
        f"got {result}",
    )


_with_temp_projects(_test_subproject_without_marker)


# Test 5: Deep cwd inside subproject resolves correctly
def _test_deep_cwd(projects_dir):
    proj = os.path.join(projects_dir, "myproj")
    sub = os.path.join(proj, "sub1")
    deep = os.path.join(sub, "src", "lib")
    os.makedirs(deep)
    open(os.path.join(sub, SUBPROJECT_MARKER), "w").close()
    result = detect_project(deep)
    test(
        "PD: deep cwd inside subproject resolves correctly",
        result == ("myproj", proj, "sub1", sub),
        f"got {result}",
    )


_with_temp_projects(_test_deep_cwd)


# Test 6: scan_subproject_states finds only marked subdirs with state files
def _test_scan_marked_only(projects_dir):
    proj = os.path.join(projects_dir, "hub")
    sub_a = os.path.join(proj, "alpha")
    sub_b = os.path.join(proj, "beta")
    sub_c = os.path.join(proj, "gamma")  # No marker
    os.makedirs(sub_a)
    os.makedirs(sub_b)
    os.makedirs(sub_c)
    # Mark alpha and beta
    open(os.path.join(sub_a, SUBPROJECT_MARKER), "w").close()
    open(os.path.join(sub_b, SUBPROJECT_MARKER), "w").close()
    # State files only for alpha and beta
    with open(os.path.join(sub_a, PROJECT_STATE_FILENAME), "w") as f:
        json.dump({"what_was_done": "alpha work", "session_count": 1}, f)
    with open(os.path.join(sub_b, PROJECT_STATE_FILENAME), "w") as f:
        json.dump({"what_was_done": "beta work", "session_count": 2}, f)
    # gamma has state but no marker — should be skipped
    with open(os.path.join(sub_c, PROJECT_STATE_FILENAME), "w") as f:
        json.dump({"what_was_done": "gamma work"}, f)

    results = scan_subproject_states(proj)
    names = [r["project_name"] for r in results]
    test(
        "PD: scan finds only marked subdirs", names == ["alpha", "beta"], f"got {names}"
    )


_with_temp_projects(_test_scan_marked_only)


# Test 7: scan_subproject_states skips unmarked dirs
def _test_scan_skips_unmarked(projects_dir):
    proj = os.path.join(projects_dir, "hub2")
    sub_x = os.path.join(proj, "x")
    sub_y = os.path.join(proj, "y")
    os.makedirs(sub_x)
    os.makedirs(sub_y)
    # No markers, no state files
    results = scan_subproject_states(proj)
    test("PD: scan returns empty for unmarked dirs", results == [], f"got {results}")


_with_temp_projects(_test_scan_skips_unmarked)


# Test 8: scan_subproject_states skips marked dirs without state files
def _test_scan_skips_no_state(projects_dir):
    proj = os.path.join(projects_dir, "hub3")
    sub = os.path.join(proj, "nosate")
    os.makedirs(sub)
    open(os.path.join(sub, SUBPROJECT_MARKER), "w").close()
    # Marker present but no state file
    results = scan_subproject_states(proj)
    test("PD: scan skips marked dirs without state", results == [], f"got {results}")


_with_temp_projects(_test_scan_skips_no_state)


# Test 9: detect_project returns 4-tuple length always
def _test_tuple_length(projects_dir):
    r1 = detect_project("/nonexistent")
    r2 = detect_project(projects_dir)
    proj = os.path.join(projects_dir, "p")
    os.makedirs(proj)
    r3 = detect_project(proj)
    test(
        "PD: detect_project always returns 4-tuple",
        all(len(r) == 4 for r in [r1, r2, r3]),
        f"lengths: {[len(r) for r in [r1, r2, r3]]}",
    )


_with_temp_projects(_test_tuple_length)


# Test 10: SUBPROJECT_MARKER constant exists
test(
    "PD: SUBPROJECT_MARKER constant is .claude-project",
    SUBPROJECT_MARKER == ".claude-project",
    f"got {SUBPROJECT_MARKER}",
)


# Test 11: Agent dir detected
def _test_agent_dir(projects_dir):
    import boot_pkg.util as _util

    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, "agents")
        agent = os.path.join(agents_dir, "researcher-alpha")
        os.makedirs(agent)
        old = _util.AGENTS_DIR
        _util.AGENTS_DIR = agents_dir
        try:
            result = detect_project(agent)
            test(
                "PD: agent dir returns (role, dir, None, None)",
                result == ("researcher-alpha", agent, None, None),
                f"got {result}",
            )
        finally:
            _util.AGENTS_DIR = old


_test_agent_dir(None)  # projects_dir unused but signature required
