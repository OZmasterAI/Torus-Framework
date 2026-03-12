"""Tests for state_type classification (C-lite Final — Rule 5b upgrade).

Deterministic keyword scanner classifies memories as ephemeral/conceptual/"".
Orthogonal to memory_type (reference/working).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.memory_classification import classify_state_type


# ── Ephemeral ────────────────────────────────────────────────────────────────


def test_ephemeral_port_running():
    """Runtime state with port + running → ephemeral."""
    assert classify_state_type("MCP server running on port 8741", "") == "ephemeral"


def test_ephemeral_process_pid():
    """Process with PID → ephemeral."""
    assert (
        classify_state_type("memory_server process started with pid 12345", "")
        == "ephemeral"
    )


def test_ephemeral_localhost_listening():
    """localhost + listening → ephemeral."""
    assert (
        classify_state_type("Server listening on localhost port 8742", "")
        == "ephemeral"
    )


def test_ephemeral_worktree_spawned():
    """worktree + spawned → ephemeral."""
    assert (
        classify_state_type("Agent spawned in worktree /tmp/memory-v2", "")
        == "ephemeral"
    )


def test_ephemeral_auto_captured_single_keyword():
    """auto-captured + 1 ephemeral keyword → ephemeral (lowered threshold)."""
    assert (
        classify_state_type("tmux pane output captured", "type:auto-captured")
        == "ephemeral"
    )


def test_ephemeral_daemon_socket():
    """daemon + socket → ephemeral."""
    assert (
        classify_state_type(
            "Memory daemon connected via socket /run/user/1000/mem.sock", ""
        )
        == "ephemeral"
    )


# ── Conceptual ───────────────────────────────────────────────────────────────


def test_conceptual_decision_architecture():
    """Content with decision + architecture → conceptual."""
    assert (
        classify_state_type("Design decision: use layered architecture for memory", "")
        == "conceptual"
    )


def test_conceptual_tag_decision():
    """type:decision tag → conceptual (tag boost +2)."""
    assert (
        classify_state_type("LanceDB uses cosine similarity", "type:decision")
        == "conceptual"
    )


def test_conceptual_tag_preference():
    """type:preference tag → conceptual."""
    assert (
        classify_state_type("User prefers short memories", "type:preference")
        == "conceptual"
    )


def test_conceptual_pattern_convention():
    """pattern + convention → conceptual."""
    assert (
        classify_state_type(
            "The naming convention pattern is snake_case for all modules", ""
        )
        == "conceptual"
    )


def test_conceptual_guideline_standard():
    """guideline + standard → conceptual."""
    assert (
        classify_state_type("The coding guideline follows the standard practice", "")
        == "conceptual"
    )


def test_conceptual_deprecated_invariant():
    """deprecated + invariant → conceptual."""
    assert (
        classify_state_type(
            "The old API is deprecated and the invariant is that IDs are stable", ""
        )
        == "conceptual"
    )


def test_conceptual_tradeoff_strategy():
    """tradeoff + strategy → conceptual."""
    assert (
        classify_state_type("The tradeoff in our strategy is speed vs accuracy", "")
        == "conceptual"
    )


# ── Unclassified ─────────────────────────────────────────────────────────────


def test_unclassified_generic():
    """Generic content → unclassified."""
    assert classify_state_type("Fixed a bug in the search function", "type:fix") == ""


def test_unclassified_mixed_tie():
    """Equal ephemeral + conceptual hits → unclassified (tie → '')."""
    assert (
        classify_state_type("The running process follows the design pattern", "") == ""
    )


def test_unclassified_no_keywords():
    """No matching keywords at all → unclassified."""
    assert (
        classify_state_type(
            "Implemented the new feature for user profiles", "type:feature"
        )
        == ""
    )


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_ephemeral_wins_over_conceptual():
    """More ephemeral than conceptual hits → ephemeral."""
    assert (
        classify_state_type(
            "Server running on port 8741, process started and listening", ""
        )
        == "ephemeral"
    )


def test_conceptual_wins_over_ephemeral():
    """More conceptual than ephemeral hits → conceptual."""
    assert (
        classify_state_type(
            "Architecture decision: the design pattern and convention for all modules",
            "",
        )
        == "conceptual"
    )


# ── False positive prevention ────────────────────────────────────────────────


def test_no_false_positive_branch_strategy():
    """'branch strategy' should NOT be ephemeral (branch removed from list)."""
    result = classify_state_type("Our branch strategy is to use feature branches", "")
    assert result != "ephemeral"


def test_no_false_positive_active_development():
    """'active development' should NOT be ephemeral (active removed from list)."""
    result = classify_state_type("This feature is in active development", "")
    assert result != "ephemeral"


def test_no_false_positive_session_analysis():
    """'session analysis' should NOT be ephemeral (session removed from list)."""
    result = classify_state_type("Session 388 analysis showed memory improvements", "")
    assert result != "ephemeral"


# ── Schema test ──────────────────────────────────────────────────────────────


def test_state_type_in_schema():
    """_KNOWLEDGE_SCHEMA includes state_type field."""
    with open(os.path.join(os.path.dirname(__file__), "..", "memory_server.py")) as f:
        for line in f:
            if "pa.field(" in line and '"state_type"' in line:
                return  # found
    assert False, "state_type field not found in _KNOWLEDGE_SCHEMA"


# ── Pipeline wiring tests ────────────────────────────────────────────────────


def test_write_pipeline_sets_state_type():
    """WritePipeline includes state_type in upsert metadata."""
    with open(
        os.path.join(os.path.dirname(__file__), "..", "shared", "write_pipeline.py")
    ) as f:
        content = f.read()
    assert "state_type" in content, "state_type not found in write_pipeline.py"
    assert "classify_state_type" in content, (
        "classify_state_type not wired in write_pipeline.py"
    )


def test_search_pipeline_accepts_state_type():
    """SearchPipeline.search() accepts state_type parameter."""
    import inspect

    from shared.search_pipeline import SearchPipeline

    sig = inspect.signature(SearchPipeline.search)
    assert "state_type" in sig.parameters, (
        "state_type param not in SearchPipeline.search()"
    )


def test_search_knowledge_accepts_state_type():
    """search_knowledge() tool accepts state_type parameter."""
    with open(os.path.join(os.path.dirname(__file__), "..", "memory_server.py")) as f:
        content = f.read()
    sk_section = content.split("def search_knowledge")[1].split("\ndef ")[0]
    assert "state_type" in sk_section, "state_type not in search_knowledge signature"
