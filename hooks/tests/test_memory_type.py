"""Tests for memory_type classification (MWP Option C — filter only, no scoring)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.memory_classification import classify_memory_type


# ── Reference classification ─────────────────────────────────────────────────


def test_classify_reference_decision():
    """type:decision tag → reference."""
    assert (
        classify_memory_type("Some decision content", "type:decision,area:framework")
        == "reference"
    )


def test_classify_reference_preference():
    """type:preference tag → reference."""
    assert classify_memory_type("User prefers X", "type:preference") == "reference"


def test_classify_reference_learning_success():
    """type:learning + outcome:success → reference."""
    assert (
        classify_memory_type("Learned something", "type:learning,outcome:success")
        == "reference"
    )


def test_classify_reference_high_salience():
    """High salience (>=0.40) without explicit reference tags → reference."""
    # "decision" keyword gives 0.25, priority:high gives 0.15 → sal=0.40
    content = "We made a decision to switch to the new approach"
    tags = "priority:high"
    assert classify_memory_type(content, tags) == "reference"


# ── Working classification ───────────────────────────────────────────────────


def test_classify_working_auto_captured():
    """type:auto-captured → working."""
    assert (
        classify_memory_type("Auto captured observation", "type:auto-captured")
        == "working"
    )


def test_classify_working_session_tag():
    """session410 tag → working."""
    assert classify_memory_type("Session notes", "session410,area:backend") == "working"


def test_classify_working_error():
    """type:error without outcome:success → working."""
    assert classify_memory_type("Something broke", "type:error") == "working"


def test_classify_working_low_salience_short():
    """Low salience (<0.15) + short content (<200 chars) → working."""
    assert classify_memory_type("short note", "area:backend") == "working"


# ── Unclassified ─────────────────────────────────────────────────────────────


def test_classify_unclassified_default():
    """Generic tags with moderate salience → unclassified."""
    # type:fix gives salience 0.15, which is >=0.15 but <0.40, and content >200
    content = (
        "Fixed a moderately important bug in the system that required careful investigation "
        * 3
    )
    tags = "type:fix,area:backend"
    assert classify_memory_type(content, tags) == ""


# ── Schema test ──────────────────────────────────────────────────────────────


def test_memory_type_in_schema():
    """_KNOWLEDGE_SCHEMA includes memory_type field."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    # Import the schema from memory_server
    import importlib
    import types

    # Read schema directly to avoid full server init
    import pyarrow as pa

    schema_fields = []
    with open(os.path.join(os.path.dirname(__file__), "..", "memory_server.py")) as f:
        for line in f:
            if "pa.field(" in line and '"memory_type"' in line:
                schema_fields.append("memory_type")
                break

    assert "memory_type" in schema_fields, (
        "memory_type field not found in _KNOWLEDGE_SCHEMA"
    )
