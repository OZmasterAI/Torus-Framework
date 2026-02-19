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

# Short labels for toggles — avoids wrapping in narrow pane
TOGGLE_SHORT = {
    "terminal_l2_always":    "Term L2",
    "context_enrichment":    "L2 enrich",
    "tg_l3_always":          "TG L3",
    "tg_enrichment":         "TG enrich",
    "tg_bot_tmux":           "TG bot",
    "gate_auto_tune":        "AutoTune",
    "budget_degradation":    "BudgetDeg",
    "chain_memory":          "ChainMem",
    "session_token_budget":  "TokBudget",
}


class StatusBar(Static):
    """Top bar: model, branch, session#, context%."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        live = self._data.live_state()
        mem = self._data.memory_stats()
        snap = self._data.statusline_snapshot()
        s = live.get("session_count", "?")
        m = mem.get("mem_count", "?")
        model = snap.get("model", "claude")
        # Shorten model name: "claude-sonnet-4-6" -> "sonnet-4-6"
        if model.startswith("claude-"):
            model = model[7:]
        ctx = snap.get("context_pct", 0)
        branch = self._data.git_branch() or "?"

        if ctx >= 70:
            ctx_col = "red"
        elif ctx >= 50:
            ctx_col = "yellow"
        else:
            ctx_col = "green"

        return (
            f" [bold]{model}[/bold]"
            f"  [dim]{branch}[/dim]"
            f"  [dim]#{s}[/dim]"
            f"  [dim]M:{m}[/dim]"
            f"  [{ctx_col}]{ctx}%[/{ctx_col}]"
        )


class HealthBar(Static):
    """Health bar + cost + duration + lines changed."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        snap = self._data.statusline_snapshot()
        state = self._data.session_state()

        health = snap.get("health_pct", 100) if snap else 100

        error_windows = state.get("error_windows", [])
        now = time.time()
        recent = sum(
            e.get("count", 1) for e in error_windows
            if isinstance(e, dict) and now - e.get("last_seen", 0) < 300
        )

        filled = health // 10
        if health >= 90:
            hc = "green"
            dot = "\u25cf"  # filled circle
        elif health >= 70:
            hc = "yellow"
            dot = "\u25cf"
        else:
            hc = "red"
            dot = "\u25cf"

        # Slim 8-block bar
        bar_filled = "\u2588" * (health // 12)
        bar_empty = "\u2591" * (8 - len(bar_filled))
        bar = f"[{hc}]{bar_filled}{bar_empty}[/{hc}]"

        parts = [f"[{hc}]{dot}[/{hc}] {bar} [dim]{health}%[/dim]"]

        if recent > 0:
            parts.append(f"[red]\u26a0 {recent}[/red]")

        if snap:
            cost = snap.get("cost_usd", 0)
            if cost:
                parts.append(f"[dim]${cost:.2f}[/dim]")
            dur = snap.get("duration_min", 0)
            if dur:
                parts.append(f"[dim]{dur}m[/dim]")
            la = snap.get("lines_added", 0)
            lr = snap.get("lines_removed", 0)
            if la or lr:
                parts.append(f"[green]+{la}[/green][dim]/[/dim][red]-{lr}[/red]")

        return " ".join(parts)


class InfoBar(Static):
    """Tokens, compression, UDS status — only shown when snapshot is fresh."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        snap = self._data.statusline_snapshot()
        if not snap:
            return ""
        ts = snap.get("ts", 0)
        age = time.time() - ts
        if age > 30:
            return f"[dim]\u231b snapshot {int(age)}s ago[/dim]"

        parts = []
        tok = snap.get("session_tokens", "0")
        if tok and tok != "0":
            last = snap.get("last_turn", "")
            s = f"[cyan]{tok}[/cyan]"
            if last:
                s += f"[dim]+{last}[/dim]"
            parts.append(s)

        cmp = snap.get("compressions", 0)
        if cmp:
            parts.append(f"[yellow]\u21ba{cmp}[/yellow]")

        uds = snap.get("uds_ok", False)
        if uds:
            parts.append("[green]\u25cf[/green][dim]UDS[/dim]")
        else:
            parts.append("[yellow]\u25cb[/yellow][dim]UDS[/dim]")

        return " [dim]\u2502[/dim] ".join(parts) if parts else ""


class SessionMetrics(Static):
    """Live session stats: tool calls, files, verification, memory freshness, mode."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        state = self._data.session_state()
        calls = state.get("total_tool_calls", 0)
        edited = len(state.get("files_edited", []))
        v_ok, v_total = self._data.verification_ratio()

        tc = state.get("tool_call_counts", {})
        top = sorted(tc.items(), key=lambda x: -x[1])[:3]

        fresh = self._data.memory_freshness()
        mode = self._data.active_mode()

        # Verification color
        if v_total == 0:
            v_str = "[dim]0/0[/dim]"
        elif v_ok == v_total:
            v_str = f"[green]{v_ok}/{v_total}[/green]"
        else:
            v_str = f"[yellow]{v_ok}/{v_total}[/yellow]"

        # Memory freshness indicator
        if fresh is None:
            mem_str = "[dim]\u2014[/dim]"
        elif fresh <= 5:
            mem_str = f"[green]\u25cf {fresh}m[/green]"
        elif fresh <= 15:
            mem_str = f"[yellow]\u25cf {fresh}m[/yellow]"
        else:
            mem_str = f"[red]\u25cb {fresh}m[/red]"

        mode_str = f"  [bold cyan]{mode}[/bold cyan]" if mode else ""

        row1 = (
            f"[dim]TC[/dim] [bold]{calls}[/bold]"
            f"  [dim]F[/dim] [bold]{edited}[/bold]"
            f"  [dim]V[/dim] {v_str}"
            f"  [dim]M[/dim] {mem_str}"
            f"{mode_str}"
        )

        if top:
            tool_parts = []
            for t, c in top:
                # shorten tool names
                short = t[:4] if len(t) > 4 else t
                tool_parts.append(f"[dim]{short}[/dim]:{c}")
            row2 = "  ".join(tool_parts)
        else:
            row2 = "[dim]no tool calls yet[/dim]"

        return f"{row1}\n [dim]{row2}[/dim]"


class GatePanel(Static):
    """Compact 2-column gate list with colored dot indicators."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        eff = self._data.gate_effectiveness()

        def gate_line(key, gid, name, gtype):
            d = eff.get(key, {})
            blocks = d.get("blocks", 0)
            overrides = d.get("overrides", 0)
            total = blocks + overrides

            # Status dot
            if total == 0:
                dot = "[dim]\u25cb[/dim]"
                stat = "[dim]  \u2014[/dim]"
            else:
                pct = int(blocks / total * 100)
                if pct >= 90:
                    dot = "[green]\u25cf[/green]"
                elif pct >= 70:
                    dot = "[yellow]\u25cf[/yellow]"
                else:
                    dot = "[red]\u25cf[/red]"
                stat = f"[dim]{blocks:>3}[/dim]"

            # Type badge
            t_badge = "[red]B[/red]" if gtype == "B" else "[yellow]A[/yellow]"
            return f" {dot}{t_badge}[dim]{gid}[/dim] {name:<10}{stat}"

        lines = ["[bold dim]GATES[/bold dim]"]
        # Render in 2-column pairs
        for i in range(0, len(GATE_INFO), 2):
            left = gate_line(*GATE_INFO[i])
            if i + 1 < len(GATE_INFO):
                right = gate_line(*GATE_INFO[i + 1])
                lines.append(f"{left}  {right}")
            else:
                lines.append(left)
        return "\n".join(lines)


class AuditPanel(Static):
    """Recent audit entries — monospace aligned, dim timestamps."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        entries = self._data.audit_tail(12)
        if not entries:
            return "[bold dim]AUDIT[/bold dim]\n [dim]no entries today[/dim]"

        lines = ["[bold dim]AUDIT[/bold dim]"]
        for entry in entries[-10:]:
            decision = entry.get("decision", "?")
            gate = entry.get("gate", "")
            tool = entry.get("tool", "?")
            ts = entry.get("timestamp", "")
            tp = ts[11:16] if len(ts) >= 16 else "     "

            # Shorten gate label
            gs = gate.split(": ", 1)[-1] if ": " in gate else gate
            # Remove "gate_NN_" prefix if present
            parts_g = gs.split("_", 2)
            if len(parts_g) == 3 and parts_g[0] == "gate":
                gs = parts_g[2][:9]
            else:
                gs = gs[:9]

            # Shorten tool name
            tool_short = tool[:8] if len(tool) > 8 else tool

            if decision == "block":
                icon = "[red]\u2715[/red]"
            elif decision == "warn":
                icon = "[yellow]\u26a0[/yellow]"
            else:
                icon = "[dim]\u00b7[/dim]"

            lines.append(
                f" {icon} [dim]{tp}[/dim] [dim]{gs:<9}[/dim] {tool_short}"
            )
        return "\n".join(lines)


class TorusApp(App):
    CSS = """
    Screen {
        background: $surface;
        overflow: hidden hidden;
    }

    StatusBar {
        height: 1;
        background: $accent-darken-2;
        color: $text;
        padding: 0 0;
    }

    HealthBar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    InfoBar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    SessionMetrics {
        height: auto;
        padding: 0 1;
    }

    GatePanel {
        height: auto;
        padding: 0 1;
    }

    AuditPanel {
        height: auto;
        padding: 0 1;
    }

    .sep {
        height: 1;
        color: $primary-darken-3;
        padding: 0 1;
    }

    /* Toggles */
    #tog-header {
        height: 1;
        color: $text-muted;
        text-style: bold;
        padding: 0 1;
    }

    .trow {
        height: 1;
        padding: 0 1;
    }

    .trow Switch {
        width: 5;
        min-width: 5;
        height: 1;
        border: none;
        background: transparent;
    }

    .tlabel {
        width: 1fr;
        content-align: left middle;
        color: $text-muted;
    }

    .tval {
        width: 4;
        content-align: center middle;
        color: $accent;
    }

    Footer {
        background: $primary-background;
        height: 1;
    }
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
            yield InfoBar(self.data)
            yield SessionMetrics(self.data)
            yield Static("[dim]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/dim]", classes="sep")
            yield GatePanel(self.data)
            yield Static("[dim]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/dim]", classes="sep")
            yield Label("[dim bold]TOGGLES[/dim bold]", id="tog-header")
            live = self.data.live_state()
            for label, key, default, desc in TOGGLES:
                short = TOGGLE_SHORT.get(key, label[:10])
                val = live.get(key, default)
                if isinstance(default, bool):
                    with Horizontal(classes="trow"):
                        yield Switch(value=bool(val), id=f"sw_{key}")
                        yield Label(short, classes="tlabel")
                else:
                    with Horizontal(classes="trow"):
                        yield Label(f"[bold]{val}[/bold]", id=f"val_{key}", classes="tval")
                        yield Label(short, classes="tlabel")
            yield Static("[dim]\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500[/dim]", classes="sep")
            yield AuditPanel(self.data)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()
        for w in (StatusBar, HealthBar, InfoBar, SessionMetrics, GatePanel, AuditPanel):
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
