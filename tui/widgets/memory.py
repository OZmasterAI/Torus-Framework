"""Memory stats widget - counts and health."""

from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class MemoryPanel(Widget):
    """Memory collection counts and health."""

    DEFAULT_CSS = """
    MemoryPanel { height: auto; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="mem_content")

    def refresh_data(self, mem_stats: dict, live_state: dict):
        count = mem_stats.get("mem_count", "?")
        issues = live_state.get("known_issues", [])
        lines = [f"Memories: {count}", f"Known issues: {len(issues)}"]
        for issue in issues:
            if "observation" in str(issue).lower() and "cap" in str(issue).lower():
                lines.append(f"  ! {issue[:60]}")
                break
        self.query_one("#mem_content", Static).update("\n".join(lines))
