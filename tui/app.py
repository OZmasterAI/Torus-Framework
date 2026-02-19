#!/usr/bin/env python3
"""Torus Framework TUI Dashboard.

Live monitoring and toggle control for the Torus self-healing framework.
Designed to run as a left tmux pane alongside Claude Code.

Launch: python3 ~/.claude/tui/app.py
  or:   bash ~/.claude/tui/launch.sh  (splits tmux left pane)

Keys: q=quit  r=refresh  t=toggles  1-8=tabs  p=pause  ?=help
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, TabbedContent, TabPane

from data import DataLayer, TOGGLES
from widgets.header_bar import HeaderBar
from widgets.toggles import TogglePanel, ToggleRow, BudgetRow
from widgets.gates import GateTable
from widgets.audit_feed import AuditFeed
from widgets.memory import MemoryPanel
from widgets.session import SessionPanel
from widgets.errors import ErrorPanel
from widgets.activity import ActivityPanel
from widgets.skills import SkillPanel
from widgets.tests import TestPanel


class TorusApp(App):
    """Torus Framework TUI Dashboard."""

    TITLE = "Torus Dashboard"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "focus_toggles", "Toggles"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("question_mark", "help", "Help"),
        Binding("1", "tab('gates')", "Gates", show=False),
        Binding("2", "tab('audit')", "Audit", show=False),
        Binding("3", "tab('memory')", "Memory", show=False),
        Binding("4", "tab('session')", "Session", show=False),
        Binding("5", "tab('errors')", "Errors", show=False),
        Binding("6", "tab('skills')", "Skills", show=False),
        Binding("7", "tab('tests')", "Tests", show=False),
        Binding("8", "tab('trend')", "Trend", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.data = DataLayer()
        self.paused = False

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical():
            yield TogglePanel(TOGGLES, self.data.live_state(), id="toggle-panel")
            with TabbedContent(id="tab-content"):
                with TabPane("Gates", id="gates"):
                    yield GateTable()
                with TabPane("Audit", id="audit"):
                    yield AuditFeed()
                with TabPane("Memory", id="memory"):
                    yield MemoryPanel()
                with TabPane("Session", id="session"):
                    yield SessionPanel()
                with TabPane("Errors", id="errors"):
                    yield ErrorPanel()
                with TabPane("Skills", id="skills"):
                    yield SkillPanel()
                with TabPane("Tests", id="tests"):
                    yield TestPanel()
                with TabPane("Trend", id="trend"):
                    yield ActivityPanel()
        yield Footer()

    def on_mount(self):
        self.set_interval(2.0, self._refresh_data)
        self._refresh_data()

    def _refresh_data(self):
        if self.paused:
            return

        live = self.data.live_state()
        mem = self.data.memory_stats()
        eff = self.data.gate_effectiveness()
        state = self.data.session_state()
        audit = self.data.audit_tail()

        try:
            self.query_one(HeaderBar).update_data(live, mem)
        except Exception:
            pass

        try:
            self.query_one(TogglePanel).refresh_data(live)
        except Exception:
            pass

        try:
            self.query_one(GateTable).refresh_data(eff)
        except Exception:
            pass

        try:
            self.query_one(AuditFeed).refresh_data(audit)
        except Exception:
            pass

        try:
            self.query_one(MemoryPanel).refresh_data(mem, live)
        except Exception:
            pass

        try:
            self.query_one(SessionPanel).refresh_data(state)
        except Exception:
            pass

        try:
            self.query_one(ErrorPanel).refresh_data(state)
        except Exception:
            pass

        try:
            self.query_one(SkillPanel).refresh_data(state)
        except Exception:
            pass

        try:
            self.query_one(TestPanel).refresh_data(state, live)
        except Exception:
            pass

        try:
            buckets = self.data.activity_buckets()
            self.query_one(ActivityPanel).refresh_data(buckets)
        except Exception:
            pass

    def on_toggle_row_changed(self, event: ToggleRow.Changed):
        self.data.set_toggle(event.key, event.value)

    def on_budget_row_changed(self, event: BudgetRow.Changed):
        self.data.set_toggle("session_token_budget", event.value)

    def action_refresh(self):
        self.data.invalidate()
        self._refresh_data()

    def action_focus_toggles(self):
        try:
            self.query_one(TogglePanel).focus()
        except Exception:
            pass

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.notify(f"Dashboard: {'PAUSED' if self.paused else 'LIVE'}")

    def action_tab(self, tab_id: str):
        try:
            tc = self.query_one(TabbedContent)
            tc.active = tab_id
        except Exception:
            pass

    def action_help(self):
        self.notify(
            "Keys: q=quit r=refresh t=toggles 1-8=tabs p=pause",
            title="Help",
            timeout=5,
        )


if __name__ == "__main__":
    app = TorusApp()
    app.run()
