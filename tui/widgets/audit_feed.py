"""Live audit feed - colour-coded gate events."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog
from rich.text import Text


class AuditFeed(Widget):
    """Tailing audit log with colour-coded entries."""

    DEFAULT_CSS = """
    AuditFeed { height: 1fr; }
    AuditFeed RichLog { height: 1fr; }
    """

    def __init__(self):
        super().__init__()
        self._seen_count = 0

    def compose(self) -> ComposeResult:
        yield RichLog(id="audit_log", wrap=True, max_lines=200)

    def refresh_data(self, entries: list):
        if len(entries) <= self._seen_count:
            return
        log = self.query_one("#audit_log", RichLog)
        new_entries = entries[self._seen_count:]
        self._seen_count = len(entries)

        for entry in new_entries:
            decision = entry.get("decision", "?")
            gate = entry.get("gate", "?")
            tool = entry.get("tool", "?")
            reason = entry.get("reason", "")[:60]
            ts = entry.get("timestamp", "")
            time_part = ts[11:19] if len(ts) >= 19 else ts

            text = Text()
            text.append(f"{time_part} ", style="dim")
            if decision == "block":
                text.append("BLOCK ", style="bold red")
            elif decision == "warn":
                text.append("WARN  ", style="yellow")
            else:
                text.append("pass  ", style="dim green")
            text.append(f"{gate[:28]:28s} ", style="bold")
            text.append(f"{tool:8s} ", style="cyan")
            text.append(reason, style="dim")
            log.write(text)
