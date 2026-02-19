"""Error patterns widget - bans, causal chains."""

from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class ErrorPanel(Widget):
    """Error patterns and strategy bans."""

    DEFAULT_CSS = """
    ErrorPanel { height: auto; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="error_content")

    def refresh_data(self, state: dict):
        bans = state.get("active_bans", [])
        patterns = state.get("error_pattern_counts", {})
        chains = state.get("pending_chain_ids", [])
        fixing = state.get("fixing_error", False)

        lines = [
            f"Active bans: {len(bans)}",
            f"Error patterns: {len(patterns)}",
            f"Pending chains: {len(chains)}",
            f"Fixing error: {'YES' if fixing else 'no'}",
        ]

        if bans:
            lines.append("")
            lines.append("Banned strategies:")
            for ban in bans[:5]:
                lines.append(f"  x {ban}")

        if patterns:
            top = sorted(patterns.items(), key=lambda x: -x[1])[:5]
            lines.append("")
            lines.append("Top error patterns:")
            for pattern, count in top:
                lines.append(f"  {pattern[:40]}: {count}x")

        self.query_one("#error_content", Static).update("\n".join(lines))
