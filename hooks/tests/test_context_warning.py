"""Tests for context threshold warning system (Option B).

Tests PostToolUse detection (_check_context_threshold) and
Stop hook verification (check_and_warn).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestContextThresholdDetection:
    """PostToolUse should detect context >= 65% and print one-time warning."""

    def test_no_warning_below_threshold(self, tmp_path, capsys):
        from tracker_pkg.orchestrator import _check_context_threshold

        snapshot = tmp_path / ".statusline_snapshot.json"
        snapshot.write_text(json.dumps({"context_pct": 50}))
        op_state = {"summary_threshold_fired": False, "context_warning_shown": False}
        _check_context_threshold(op_state, str(snapshot))
        assert not op_state.get("context_warning_shown")
        assert capsys.readouterr().out == ""

    def test_warning_at_threshold(self, tmp_path, capsys):
        from tracker_pkg.orchestrator import _check_context_threshold

        snapshot = tmp_path / ".statusline_snapshot.json"
        snapshot.write_text(json.dumps({"context_pct": 67}))
        op_state = {"summary_threshold_fired": False, "context_warning_shown": False}
        _check_context_threshold(op_state, str(snapshot))
        assert op_state["context_warning_shown"]
        assert op_state["summary_threshold_fired"]
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "67%" in out
        assert "/working-summary" in out

    def test_warning_fires_only_once(self, tmp_path, capsys):
        from tracker_pkg.orchestrator import _check_context_threshold

        snapshot = tmp_path / ".statusline_snapshot.json"
        snapshot.write_text(json.dumps({"context_pct": 72}))
        op_state = {"summary_threshold_fired": True, "context_warning_shown": True}
        _check_context_threshold(op_state, str(snapshot))
        assert capsys.readouterr().out == ""

    def test_no_warning_when_snapshot_missing(self, tmp_path, capsys):
        from tracker_pkg.orchestrator import _check_context_threshold

        op_state = {"summary_threshold_fired": False, "context_warning_shown": False}
        _check_context_threshold(op_state, str(tmp_path / "nonexistent.json"))
        assert not op_state.get("context_warning_shown")
        assert capsys.readouterr().out == ""

    def test_exact_threshold_boundary(self, tmp_path, capsys):
        from tracker_pkg.orchestrator import _check_context_threshold

        snapshot = tmp_path / ".statusline_snapshot.json"
        snapshot.write_text(json.dumps({"context_pct": 65}))
        op_state = {"summary_threshold_fired": False, "context_warning_shown": False}
        _check_context_threshold(op_state, str(snapshot))
        assert op_state["context_warning_shown"]
        assert "65%" in capsys.readouterr().out


class TestStopHookWarning:
    """Stop hook should verify summary was written and print formatted warning."""

    def test_no_output_when_threshold_not_fired(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {"summary_threshold_fired": False}
        check_and_warn(op_state, summary_size=0, context_pct=30)
        assert capsys.readouterr().err == ""

    def test_success_message_when_summary_written(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": False,
        }
        check_and_warn(op_state, summary_size=4200, context_pct=67)
        err = capsys.readouterr().err
        assert "## WARNING ##" in err
        assert "67%" in err
        assert "4,200" in err
        assert "/clear" in err
        assert op_state["summary_warning_shown"]

    def test_error_message_when_summary_not_written(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": False,
        }
        check_and_warn(op_state, summary_size=100, context_pct=67)
        err = capsys.readouterr().err
        assert "!! WARNING !!" in err
        assert "no summary written" in err.lower()

    def test_no_output_when_summary_small_but_threshold_not_fired(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {"summary_threshold_fired": False}
        check_and_warn(op_state, summary_size=100, context_pct=50)
        assert capsys.readouterr().err == ""


class TestStopHookClearReminder:
    """Stop hook should remind user to /clear on subsequent turns."""

    def test_clear_reminder_when_summary_written_context_still_high(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": True,
        }
        check_and_warn(op_state, summary_size=4200, context_pct=72)
        err = capsys.readouterr().err
        assert "/clear not run" in err
        assert "72%" in err

    def test_no_clear_reminder_on_first_fire(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": False,
        }
        check_and_warn(op_state, summary_size=4200, context_pct=67)
        err = capsys.readouterr().err
        assert "## WARNING ##" in err  # First time = summary confirmation
        assert "/clear not run" not in err

    def test_no_reminder_after_clear(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": True,
        }
        check_and_warn(
            op_state, summary_size=4200, context_pct=10
        )  # Low = /clear was run
        assert capsys.readouterr().err == ""
        # Flags should be reset
        assert not op_state["summary_threshold_fired"]
        assert not op_state["context_warning_shown"]
        assert not op_state["summary_warning_shown"]

    def test_flags_reset_when_context_drops(self, capsys):
        from context_threshold_stop import check_and_warn

        op_state = {
            "summary_threshold_fired": True,
            "context_warning_shown": True,
            "summary_warning_shown": True,
        }
        check_and_warn(op_state, summary_size=4200, context_pct=30)
        assert not op_state["summary_threshold_fired"]
        assert not op_state["summary_warning_shown"]
