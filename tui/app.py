#!/usr/bin/env python3
"""Torus Framework — Monitoring Dashboard (Textual)

Minimal single-column layout optimized for narrow (~25%) tmux pane.

Launch: bash ~/.claude/tui/launch.sh  (safe — splits tmux)
  NOT:  python3 tui/app.py from Claude's Bash tool (kills session)
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.widgets import Static, Switch, Label, Footer
from textual.containers import Horizontal, VerticalScroll
from textual import on

from data import DataLayer, TOGGLES

GATE_INFO = [
    ("gate_01_read_before_edit",    "01", "ReadB4Edit",  "B"),
    ("gate_02_no_destroy",          "02", "NoDestroy",   "B"),
    ("gate_03_test_before_deploy",  "03", "TestDeploy",  "B"),
    ("gate_04_memory_first",        "04", "MemFirst",    "B"),
    ("gate_05_proof_before_fixed",  "05", "ProofFix",    "B"),
    ("gate_06_save_fix",            "06", "SaveFix",     "A"),
    ("gate_07_critical_file_guard", "07", "CritFile",    "B"),
    ("gate_09_strategy_ban",        "09", "StratBan",    "B"),
    ("gate_10_model_enforcement",   "10", "ModelCost",   "B"),
    ("gate_11_rate_limit",          "11", "RateLimit",   "B"),
    ("gate_12_plan_mode_save",      "12", "PlanSave",    "A"),
    ("gate_13_workspace_isolation", "13", "Isolation",   "B"),
    ("gate_14_confidence_check",    "14", "Confidence",  "B"),
    ("gate_15_causal_chain",        "15", "Causal",      "B"),
    ("gate_16_code_quality",        "16", "CodeQual",    "B"),
]


class StatusBar(Static):
    """Top bar: session, health, context."""

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
        t_col = "green" if f == 0 else "red"
        return (
            f"[bold]S{s}[/bold]  "
            f"T:[{t_col}]{t}[/{t_col}]  "
            f"M:[cyan]{m}[/cyan]  "
            f"G:[green]15[/green]"
        )


class HealthBar(Static):
    """Framework health + error velocity."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        state = self._data.session_state()
        live = self._data.live_state()
        mem = self._data.memory_stats()

        mem_ok = isinstance(mem.get("mem_count", 0), int) and mem.get("mem_count", 0) > 0
        health = 100 if mem_ok else 85

        error_windows = state.get("error_windows", [])
        now = time.time()
        recent = sum(
            e.get("count", 1) for e in error_windows
            if isinstance(e, dict) and now - e.get("last_seen", 0) < 300
        )
        total_err = sum(e.get("count", 1) for e in error_windows if isinstance(e, dict))

        filled = health // 10
        hc = "green" if health >= 90 else "yellow" if health >= 70 else "red"
        bar = f"[{hc}]{'\u2588' * filled}{'\u2591' * (10 - filled)} {health}%[/{hc}]"

        parts = [f"HP:{bar}"]
        if recent > 0:
            parts.append(f"[red]ERR:{recent}[/red]")
        elif total_err > 0:
            parts.append(f"[yellow]err:{total_err}[/yellow]")

        issues = live.get("known_issues", [])
        if issues:
            parts.append(f"[dim]issues:{len(issues)}[/dim]")

        return "  ".join(parts)


class SessionMetrics(Static):
    """Live session stats."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        state = self._data.session_state()
        calls = state.get("total_tool_calls", 0)
        edited = len(state.get("files_edited", []))
        verified = len(state.get("verified_fixes", []))
        pending = len(state.get("pending_verification", []))

        tc = state.get("tool_call_counts", {})
        top = sorted(tc.items(), key=lambda x: -x[1])[:3]
        tool_str = " ".join(f"[dim]{t}[/dim]:{c}" for t, c in top) if top else "[dim]none[/dim]"

        return (
            f"[bold dim]SESSION[/bold dim]\n"
            f" TC:{calls}  Files:{edited}  V:{verified}/{verified+pending}\n"
            f" {tool_str}"
        )


class GatePanel(Static):
    """Compact gate list."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        eff = self._data.gate_effectiveness()
        lines = ["[bold dim]GATES[/bold dim]"]
        for key, gid, name, gtype in GATE_INFO:
            d = eff.get(key, {})
            blocks = d.get("blocks", 0)
            overrides = d.get("overrides", 0)
            total = blocks + overrides
            if total == 0:
                bar = "[dim]\u2591\u2591\u2591\u2591\u2591[/dim]"
                stat = ""
            else:
                pct = int(blocks / total * 100)
                fl = pct // 20
                c = "green" if pct >= 90 else "yellow" if pct >= 70 else "red"
                bar = f"[{c}]{'\u2588' * fl}{'\u2591' * (5 - fl)}[/{c}]"
                stat = f"[dim]{blocks}[/dim]"
            t = "[red]B[/red]" if gtype == "B" else "[yellow]A[/yellow]"
            lines.append(f" {gid} {bar} {name:<11}{t} {stat}")
        return "\n".join(lines)


class AuditPanel(Static):
    """Recent audit feed."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        entries = self._data.audit_tail(10)
        if not entries:
            return "[bold dim]AUDIT[/bold dim]\n [dim]no entries today[/dim]"
        lines = ["[bold dim]AUDIT[/bold dim]"]
        for entry in entries[-8:]:
            decision = entry.get("decision", "?")
            gate = entry.get("gate", "")
            tool = entry.get("tool", "?")
            ts = entry.get("timestamp", "")
            tp = ts[11:16] if len(ts) >= 16 else ""
            gs = gate.split(": ", 1)[-1][:12] if ": " in gate else gate[:12]
            if decision == "block":
                icon = "[red]X[/red]"
            elif decision == "warn":
                icon = "[yellow]![/yellow]"
            else:
                icon = "[dim].[/dim]"
            lines.append(f" {icon} {tp} {gs:<12} {tool}")
        return "\n".join(lines)


class TorusApp(App):
    CSS = """
    Screen { background: $surface; }
    StatusBar { height: 1; background: $accent; color: $text; padding: 0 1; }
    HealthBar { height: 1; padding: 0 1; }
    SessionMetrics { height: auto; padding: 0 1; }
    GatePanel { height: auto; padding: 0 1; }
    AuditPanel { height: auto; padding: 0 1; }
    #tog-label { color: $text-muted; text-style: bold; padding: 0 1; height: 1; }
    .trow { height: 1; padding: 0 1; }
    .trow Label { width: 1fr; content-align: left middle; }
    .trow Switch { width: auto; }
    .tdesc { color: $text-muted; padding: 0 1 0 3; height: 1; }
    .tval { width: auto; content-align: right middle; color: $accent; }
    .sep { height: 1; color: $accent-darken-2; padding: 0 1; }
    Footer { background: $primary-background; }
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
        yield HealthBar(self.data)
        with VerticalScroll():
            yield SessionMetrics(self.data)
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield GatePanel(self.data)
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield Label("TOGGLES", id="tog-label")
            live = self.data.live_state()
            for label, key, default, desc in TOGGLES:
                val = live.get(key, default)
                with Horizontal(classes="trow"):
                    yield Label(label)
                    if isinstance(default, bool):
                        yield Switch(value=bool(val), id=f"sw_{key}")
                    else:
                        display = str(val) if val else "0"
                        yield Label(display, id=f"val_{key}", classes="tval")
                yield Label(f"[dim]{desc}[/dim]", classes="tdesc")
            yield Static("[dim]\u2500[/dim]", classes="sep")
            yield AuditPanel(self.data)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()
        for w in (StatusBar, HealthBar, SessionMetrics, GatePanel, AuditPanel):
            try:
                self.query_one(w).refresh()
            except Exception:
                pass
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
        sid = event.switch.id or ""
        if sid.startswith("sw_"):
            key = sid[3:]
            self.data.set_toggle(key, event.value)
            self.notify(f"{key} {'ON' if event.value else 'OFF'}", timeout=2)

    def action_refresh(self) -> None:
        self._refresh()
        self.notify("Refreshed", timeout=1)

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.notify("PAUSED" if self.paused else "LIVE")


if __name__ == "__main__":
    TorusApp().run()
