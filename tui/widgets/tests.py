"""Test run info widget."""

import time
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class TestPanel(Widget):
    """Last test run information."""

    DEFAULT_CSS = """
    TestPanel { height: auto; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="test_content")

    def refresh_data(self, state: dict, live_state: dict):
        last_run = state.get("last_test_run", 0)
        exit_code = state.get("last_test_exit_code")
        test_count = live_state.get("test_count", "?")
        failures = live_state.get("test_failures", 0)
        last_cmd = state.get("last_test_command", "")

        if last_run > 0:
            ago = int(time.time() - last_run)
            if ago < 60:
                ago_str = f"{ago}s ago"
            elif ago < 3600:
                ago_str = f"{ago // 60}m ago"
            else:
                ago_str = f"{ago // 3600}h ago"
        else:
            ago_str = "never"

        status = "PASS" if exit_code == 0 else ("FAIL" if exit_code else "unknown")

        lines = [
            f"Test count: {test_count}",
            f"Failures: {failures}",
            f"Last run: {ago_str}",
            f"Exit code: {exit_code if exit_code is not None else 'n/a'}",
            f"Status: {status}",
        ]
        if last_cmd:
            lines.append(f"Command: {last_cmd[:50]}")

        self.query_one("#test_content", Static).update("\n".join(lines))
