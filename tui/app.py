#!/usr/bin/env python3
"""Torus Framework — Monitoring Dashboard (Textual)

Minimal single-column layout optimized for narrow (~25%) tmux pane.

Launch: python3 ~/.claude/tui/app.py
  or:   bash ~/.claude/tui/launch.sh
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.widgets import Static, Switch, Label, Footer
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import on
from rich.text import Text

from data import DataLayer, TOGGLES

# Gate info: (effectiveness_key, display_id, display_name, type)
GATE_INFO = [
    ("gate_01_read_before_edit",    "G01", "ReadB4Edit",    "B"),
    ("gate_02_no_destroy",          "G02", "NoDestroy",     "B"),
    ("gate_03_test_before_deploy",  "G03", "TestB4Deploy",  "B"),
    ("gate_04_memory_first",        "G04", "MemFirst",      "B"),
    ("gate_05_proof_before_fixed",  "G05", "ProofB4Fix",    "B"),
    ("gate_06_save_fix",            "G06", "SaveFix",       "A"),
    ("gate_07_critical_file_guard", "G07", "CritFile",      "B"),
    ("gate_09_strategy_ban",        "G09", "StratBan",      "B"),
    ("gate_10_model_enforcement",   "G10", "ModelCost",     "B"),
    ("gate_11_rate_limit",          "G11", "RateLimit",     "B"),
    ("gate_12_plan_mode_save",      "G12", "PlanSave",      "A"),
    ("gate_13_workspace_isolation", "G13", "Isolation",     "B"),
    ("gate_14_confidence_check",    "G14", "Confidence",    "B"),
    ("gate_15_causal_chain",        "G15", "CausalChain",   "B"),
    ("gate_16_code_quality",        "G16", "CodeQual",      "B"),
]


class StatusBar(Static):
    """Single-line status: session | tests | memories."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        live = self._data.live_state()
        mem = self._data.memory_stats()
        s = live.get("session_count", "?")
        t = live.get("test_count", "?")
        f = live.get("test_failures", 0)
        m = mem.get("mem_count", "?")
        t_str = f"[green]{t}[/green]" if f == 0 else f"[red]{t} ({f}F)[/red]"
        return f"[bold]S{s}[/bold] | T:{t_str} | M:{m} | G:15"


class GatePanel(Static):
    """Compact gate list with mini effectiveness bars."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        eff_data = self._data.gate_effectiveness()
        lines = ["[bold dim]GATES[/bold dim]"]
        for gate_key, gid, name, gtype in GATE_INFO:
            d = eff_data.get(gate_key, {})
            blocks = d.get("blocks", 0)
            overrides = d.get("overrides", 0)
            total = blocks + overrides
            if total == 0:
                bar = "[dim]\u2591\u2591\u2591\u2591\u2591[/dim]"
                stat = ""
            else:
                eff = int(blocks / total * 100)
                filled = eff // 20
                color = "green" if eff >= 90 else "yellow" if eff >= 70 else "red"
                bar = f"[{color}]{'\u2588' * filled}{'\u2591' * (5 - filled)}[/{color}]"
                stat = f"[dim]{blocks}b[/dim]"
            t = "[red]B[/red]" if gtype == "B" else "[yellow]A[/yellow]"
            lines.append(f" {gid} {bar} {name:<12} {t} {stat}")
        return "\n".join(lines)


class AuditPanel(Static):
    """Recent audit entries."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        entries = self._data.audit_tail(15)
        if not entries:
            return "[dim]No audit entries today[/dim]"
        lines = ["[bold dim]AUDIT[/bold dim]"]
        for entry in entries[-12:]:
            decision = entry.get("decision", "?")
            gate = entry.get("gate", "?")
            tool = entry.get("tool", "?")
            ts = entry.get("timestamp", "")
            time_part = ts[11:16] if len(ts) >= 16 else ""
            # Shorten gate name
            g_short = gate.split(": ", 1)[-1][:14] if ": " in gate else gate[:14]
            if decision == "block":
                icon = "[red]X[/red]"
            elif decision == "warn":
                icon = "[yellow]![/yellow]"
            else:
                icon = "[dim].[/dim]"
            lines.append(f" {icon} {time_part} {g_short:<14} {tool}")
        return "\n".join(lines)


class SessionPanel(Static):
    """Current session info."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        live = self._data.live_state()
        state = self._data.session_state()
        calls = state.get("total_tool_calls", 0)
        edited = len(state.get("files_edited", []))
        pending = len(state.get("pending_verification", []))
        verified = len(state.get("verified_fixes", []))
        tool_counts = state.get("tool_call_counts", {})

        lines = ["[bold dim]SESSION[/bold dim]"]
        lines.append(f" Calls: {calls}  Files: {edited}")
        lines.append(f" Verified: {verified}  Pending: {pending}")
        if tool_counts:
            top = sorted(tool_counts.items(), key=lambda x: -x[1])[:4]
            lines.append(" " + " ".join(f"{t}:{c}" for t, c in top))
        return "\n".join(lines)


class TorusApp(App):
    CSS = """
    Screen { background: $surface; }
    StatusBar { height: 1; background: $accent; color: $text; padding: 0 1; }
    .toggle-row { height: 2; padding: 0 1; }
    .toggle-row Label { width: 1fr; content-align: left middle; }
    .toggle-row Switch { width: auto; }
    .toggle-value { width: auto; content-align: right middle; color: $accent; }
    .section { padding: 0 0 1 0; }
    GatePanel { height: auto; padding: 0 1; }
    AuditPanel { height: auto; padding: 0 1; }
    SessionPanel { height: auto; padding: 0 1; }
    #toggles-label { color: $text-muted; text-style: bold; padding: 0 1; height: 1; }
    Footer { background: $primary-background; }
    .sep { height: 1; color: $accent-darken-2; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("p", "toggle_pause", "Pause"),
    ]

    def __init__(self):
        super().__init__()
        self.data = DataLayer()
        self.paused = False

    def compose(self) -> ComposeResult:
        yield StatusBar(self.data)
        with VerticalScroll():
            yield GatePanel(self.data)
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield Label("TOGGLES", id="toggles-label")
            live = self.data.live_state()
            for label, key, default, desc in TOGGLES:
                val = live.get(key, default)
                with Horizontal(classes="toggle-row"):
                    yield Label(label)
                    if isinstance(default, bool):
                        yield Switch(value=bool(val), id=f"sw_{key}")
                    else:
                        display = str(val) if val else "0"
                        yield Label(display, id=f"val_{key}", classes="toggle-value")
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield AuditPanel(self.data)
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield SessionPanel(self.data)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()
        for widget_type in (StatusBar, GatePanel, AuditPanel, SessionPanel):
            try:
                self.query_one(widget_type).refresh()
            except Exception:
                pass
        # Sync toggle states from LIVE_STATE
        live = self.data.live_state()
        for _, key, default, _ in TOGGLES:
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
                    lbl.update(str(val) if val else "0")
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
        self.notify("Refreshed", timeout=1)

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.notify("PAUSED" if self.paused else "LIVE")


if __name__ == "__main__":
    TorusApp().run()
