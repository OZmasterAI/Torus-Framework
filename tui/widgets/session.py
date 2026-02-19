"""Session info widget - tool counts, verification, edit hotspots."""

import os
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class SessionPanel(Widget):
    """Session state overview."""

    DEFAULT_CSS = """
    SessionPanel { height: auto; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="session_content")

    def refresh_data(self, state: dict):
        total_calls = state.get("total_tool_calls", 0)
        tool_counts = state.get("tool_call_counts", {})
        pending = state.get("pending_verification", [])
        verified = state.get("verified_fixes", [])
        files_edited = state.get("files_edited", [])
        tokens = state.get("session_token_estimate", 0)

        lines = [
            f"Tool calls: {total_calls}",
            f"Tokens est: {tokens:,}",
            f"Pending verify: {len(pending)}",
            f"Verified fixes: {len(verified)}",
            f"Files edited: {len(files_edited)}",
        ]

        if tool_counts:
            top = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
            lines.append("")
            lines.append("Top tools:")
            for tool, count in top:
                lines.append(f"  {tool}: {count}")

        edit_streak = state.get("edit_streak", {})
        if edit_streak:
            hot = sorted(edit_streak.items(), key=lambda x: -x[1])[:3]
            lines.append("")
            lines.append("Edit hotspots:")
            for fpath, count in hot:
                short = os.path.basename(fpath) if "/" in fpath else fpath
                lines.append(f"  {short}: {count}x")

        self.query_one("#session_content", Static).update("\n".join(lines))
