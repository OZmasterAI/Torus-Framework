"""Header status bar: session, tests, health, memories."""

from textual.widgets import Static


class HeaderBar(Static):
    """One-line status strip at the top of the dashboard."""

    DEFAULT_CSS = """
    HeaderBar {
        dock: top;
        height: 1;
        background: $primary-background;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    """

    def update_data(self, live_state: dict, mem_stats: dict):
        session = live_state.get("session_count", "?")
        tests = live_state.get("test_count", "?")
        failures = live_state.get("test_failures", 0)
        mem_count = mem_stats.get("mem_count", "?")
        status = live_state.get("status", "?")

        test_str = f"{tests}" if failures == 0 else f"{tests} ({failures} FAIL)"
        self.update(
            f" S{session} | Tests: {test_str} | Mem: {mem_count} | {status.upper()}"
        )
