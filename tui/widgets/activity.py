"""Activity sparkline - 24h gate activity."""

from textual.widgets import Static, Sparkline
from textual.widget import Widget
from textual.app import ComposeResult


class ActivityPanel(Widget):
    """24h gate activity sparkline."""

    DEFAULT_CSS = """
    ActivityPanel { height: 5; padding: 0 1; }
    ActivityPanel Static { height: 1; }
    ActivityPanel Sparkline { height: 3; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Activity (24h, 30m buckets)")
        yield Sparkline([], id="activity_spark")

    def refresh_data(self, buckets: list):
        spark = self.query_one("#activity_spark", Sparkline)
        spark.data = buckets if buckets else [0]
