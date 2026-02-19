#!/usr/bin/env python3
"""Torus Framework — Monitoring Dashboard (Textual)

Live version of the preview dashboard — same visual style, real data.
Sidebar: toggles + memory stats. Main: gate table + tabbed content.

Launch: python3 ~/.claude/tui/app.py
  or:   bash ~/.claude/tui/launch.sh
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.widgets import (
    Header, Footer, DataTable, Switch, Static, Label, TabbedContent, TabPane
)
from textual.containers import Horizontal, Vertical
from textual import on
from rich.text import Text

from data import DataLayer, TOGGLES

# Gate info: (effectiveness_key, display_id, display_name, type)
GATE_INFO = [
    ("gate_01_read_before_edit",    "G1",  "Read Before Edit",    "Blocking"),
    ("gate_02_no_destroy",          "G2",  "No Destroy",          "Blocking"),
    ("gate_03_test_before_deploy",  "G3",  "Test Before Deploy",  "Blocking"),
    ("gate_04_memory_first",        "G4",  "Memory First",        "Blocking"),
    ("gate_05_proof_before_fixed",  "G5",  "Proof Before Fixed",  "Blocking"),
    ("gate_06_save_fix",            "G6",  "Save Verified Fix",   "Advisory"),
    ("gate_07_critical_file_guard", "G7",  "Critical File Guard", "Blocking"),
    ("gate_09_strategy_ban",        "G9",  "Strategy Ban",        "Blocking"),
    ("gate_10_model_enforcement",   "G10", "Model Cost Guard",    "Blocking"),
    ("gate_11_rate_limit",          "G11", "Rate Limit",          "Blocking"),
    ("gate_12_plan_mode_save",      "G12", "Plan Mode Save",      "Advisory"),
    ("gate_13_workspace_isolation", "G13", "Workspace Isolation", "Blocking"),
    ("gate_14_confidence_check",    "G14", "Confidence Check",    "Blocking"),
    ("gate_15_causal_chain",        "G15", "Causal Chain",        "Blocking"),
    ("gate_16_code_quality",        "G16", "Code Quality",        "Blocking"),
]


class TorusHeader(Static):
    DEFAULT_CSS = """
    TorusHeader {
        background: $accent;
        color: $text;
        padding: 0 2;
        text-align: center;
        height: 3;
    }
    """

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        live = self._data.live_state()
        mem = self._data.memory_stats()
        session = live.get("session_count", "?")
        tests = live.get("test_count", "?")
        failures = live.get("test_failures", 0)
        memories = mem.get("mem_count", "?")
        test_str = str(tests) if failures == 0 else f"{tests} ({failures} FAIL)"
        return (
            f"Torus Framework \u2014 Session {session}  |  "
            f"Tests: {test_str}  |  Gates: 15  |  Memories: {memories}"
        )


class MemoryStats(Static):
    DEFAULT_CSS = "MemoryStats { padding: 1 2; height: auto; }"

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        mem = self._data.memory_stats()
        live = self._data.live_state()
        count = mem.get("mem_count", 0)
        issues = live.get("known_issues", [])
        return (
            "[bold cyan]Memory Stats[/bold cyan]\n"
            f"  Total memories : [green]{count}[/green]\n"
            f"  Collections    : knowledge, observations\n"
            f"  Known issues   : {len(issues)}\n"
            f"  Status         : [green]RUNNING[/green]"
        )


class TorusApp(App):
    CSS = """
    Screen { background: $surface; }
    #sidebar {
        width: 30;
        background: $panel;
        border-right: solid $accent;
        padding: 1;
    }
    #sidebar Label { color: $text-muted; margin-bottom: 1; }
    #main { width: 1fr; }
    DataTable { height: 1fr; }
    .toggle-row { height: 3; padding: 0 1; }
    .toggle-label { width: 1fr; content-align: left middle; }
    .toggle-value { width: auto; content-align: right middle; color: $accent; }
    MemoryStats { border: solid $accent; margin: 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("p", "toggle_pause", "Pause"),
        ("question_mark", "help", "Help"),
        ("1", "tab('gates-tab')", "Gates"),
        ("2", "tab('audit-tab')", "Audit"),
        ("3", "tab('session-tab')", "Session"),
    ]

    def __init__(self):
        super().__init__()
        self.data = DataLayer()
        self.paused = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield TorusHeader(self.data)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("[ TOGGLES ]")
                live = self.data.live_state()
                for label, key, default, desc in TOGGLES:
                    val = live.get(key, default)
                    with Horizontal(classes="toggle-row"):
                        yield Label(label, classes="toggle-label")
                        if isinstance(default, bool):
                            yield Switch(value=bool(val), id=f"sw_{key}")
                        else:
                            # Numeric toggles (e.g. session_token_budget)
                            display = str(val) if val else "0"
                            yield Label(display, id=f"val_{key}", classes="toggle-value")
                yield MemoryStats(self.data)
            with Vertical(id="main"):
                with TabbedContent("Gates", "Audit", "Session"):
                    with TabPane("Gates", id="gates-tab"):
                        yield DataTable(id="gate-table", zebra_stripes=True)
                    with TabPane("Audit", id="audit-tab"):
                        yield Static("", id="audit-panel")
                    with TabPane("Session", id="session-tab"):
                        yield Static("", id="session-panel")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#gate-table", DataTable)
        table.add_columns("ID", "Gate Name", "Type", "Effectiveness", "Actions")
        self._populate_gates()
        self.set_interval(2.0, self._refresh)

    def _bar(self, pct: int) -> Text:
        filled = pct // 10
        color = "green" if pct >= 90 else "yellow" if pct >= 75 else "red"
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        return Text(f"{bar} {pct}%", style=color)

    def _populate_gates(self):
        table = self.query_one("#gate-table", DataTable)
        table.clear()
        eff_data = self.data.gate_effectiveness()

        for gate_key, gid, name, gtype in GATE_INFO:
            data = eff_data.get(gate_key, {})
            blocks = data.get("blocks", 0)
            overrides = data.get("overrides", 0)
            total = blocks + overrides
            eff = int((blocks / total * 100) if total > 0 else 100)

            type_text = (
                Text(gtype, style="bold red")
                if gtype == "Blocking"
                else Text(gtype, style="yellow")
            )

            if total == 0:
                eff_bar = Text("\u2591" * 10 + " --", style="dim")
                actions = "no data"
            else:
                eff_bar = self._bar(eff)
                actions = f"{blocks} blocked"

            table.add_row(gid, name, type_text, eff_bar, actions)

    def _build_audit_text(self) -> str:
        entries = self.data.audit_tail(30)
        if not entries:
            return "[dim]No audit entries today[/dim]"
        lines = ["[bold cyan]Audit Feed (today)[/bold cyan]\n"]
        for entry in entries[-20:]:
            decision = entry.get("decision", "?")
            gate = entry.get("gate", "?")[:25]
            tool = entry.get("tool", "?")
            reason = entry.get("reason", "")[:40]
            ts = entry.get("timestamp", "")
            time_part = ts[11:19] if len(ts) >= 19 else ts
            if decision == "block":
                icon = "[red][X][/red]"
            elif decision == "warn":
                icon = "[yellow][!][/yellow]"
            else:
                icon = "[green][ ][/green]"
            lines.append(f"  {icon} {time_part}  {gate}  {tool}  {reason}")
        return "\n".join(lines)

    def _build_session_text(self) -> str:
        live = self.data.live_state()
        state = self.data.session_state()
        session = live.get("session_count", "?")
        tests = live.get("test_count", "?")
        failures = live.get("test_failures", 0)
        memories = self.data.memory_stats().get("mem_count", "?")
        total_calls = state.get("total_tool_calls", 0)
        tokens = state.get("session_token_estimate", 0)
        pending = len(state.get("pending_verification", []))
        verified = len(state.get("verified_fixes", []))
        edited = len(state.get("files_edited", []))

        lines = [
            f"[bold cyan]Session {session} Summary[/bold cyan]\n",
            f"  Branch      : self-evolve-test-branch",
            f"  Tests total : [green]{tests}[/green] ({failures} failures)",
            f"  Gates active: [green]15[/green] / 15",
            f"  Memories    : [green]{memories}[/green]",
            f"  Tool calls  : {total_calls}",
            f"  Tokens est  : {tokens:,}",
            f"  Pending     : {pending}  |  Verified: {verified}",
            f"  Files edited: {edited}",
        ]

        # Top tools
        tool_counts = state.get("tool_call_counts", {})
        if tool_counts:
            lines.append("\n[bold]Top Tools[/bold]")
            for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  {tool}: {count}")

        return "\n".join(lines)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()

        # Refresh header + memory (they use render())
        try:
            self.query_one(TorusHeader).refresh()
            self.query_one(MemoryStats).refresh()
        except Exception:
            pass

        # Refresh gates
        try:
            self._populate_gates()
        except Exception:
            pass

        # Refresh sidebar toggle states
        live = self.data.live_state()
        for _label, key, default, _desc in TOGGLES:
            val = live.get(key, default)
            if isinstance(default, bool):
                try:
                    sw = self.query_one(f"#sw_{key}", Switch)
                    if sw.value != bool(val):
                        sw.value = bool(val)
                except Exception:
                    pass
            else:
                try:
                    lbl = self.query_one(f"#val_{key}", Label)
                    display = str(val) if val else "0"
                    lbl.update(display)
                except Exception:
                    pass

        # Refresh audit + session panels
        try:
            self.query_one("#audit-panel", Static).update(self._build_audit_text())
        except Exception:
            pass
        try:
            self.query_one("#session-panel", Static).update(self._build_session_text())
        except Exception:
            pass

    @on(Switch.Changed)
    def on_switch_changed(self, event: Switch.Changed) -> None:
        switch_id = event.switch.id or ""
        if switch_id.startswith("sw_"):
            key = switch_id[3:]
            self.data.set_toggle(key, event.value)
            state = "ON" if event.value else "OFF"
            self.notify(f"{key} \u2192 {state}", timeout=2)

    def action_refresh(self) -> None:
        self._refresh()
        self.notify("Dashboard refreshed", timeout=1)

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
        self.notify("q=quit r=refresh p=pause 1=gates 2=audit 3=session", timeout=5)


if __name__ == "__main__":
    TorusApp().run()
