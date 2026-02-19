#!/usr/bin/env python3
"""Torus Framework — Terminal Dashboard (Textual)

Mirrors the statusline's terminal aesthetic: pipe-delimited, emoji-tagged,
compact text. Refreshes every 2s from the same data sources.

Layout: statusline → gates → audit → toggles (clickable)

Launch: bash ~/.claude/tui/launch.sh  (safe — splits tmux)
  NOT:  python3 tui/app.py from Claude's Bash tool (kills session)
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.widgets import Static, Footer
from textual.containers import VerticalScroll
from textual import on
from textual.message import Message

from data import DataLayer, TOGGLES

GATE_INFO = [
    ("gate_01_read_before_edit",    "01", "ReadB4Ed",   "B"),
    ("gate_02_no_destroy",          "02", "NoDstry",    "B"),
    ("gate_03_test_before_deploy",  "03", "TstDply",    "B"),
    ("gate_04_memory_first",        "04", "MemFst",     "B"),
    ("gate_05_proof_before_fixed",  "05", "Proof",      "B"),
    ("gate_06_save_fix",            "06", "SaveFx",     "A"),
    ("gate_07_critical_file_guard", "07", "CritFl",     "B"),
    ("gate_09_strategy_ban",        "09", "StrBan",     "B"),
    ("gate_10_model_enforcement",   "10", "Model",      "B"),
    ("gate_11_rate_limit",          "11", "RtLmt",      "B"),
    ("gate_12_plan_mode_save",      "12", "PlnSv",      "A"),
    ("gate_13_workspace_isolation", "13", "Isoltn",     "B"),
    ("gate_14_confidence_check",    "14", "Confid",     "B"),
    ("gate_15_causal_chain",        "15", "Causal",     "B"),
    ("gate_16_code_quality",        "16", "CdQual",     "B"),
    ("gate_17_injection_defense",   "17", "InjDef",     "B"),
]

# Toggle display: (key, short_label, is_bool, description)
TOGGLE_DISPLAY = [
    ("terminal_l2_always",   "L2",     True,  "FTS5 search"),
    ("context_enrichment",   "Enrich", True,  "Terminal ctx"),
    ("tg_l3_always",         "TG",     True,  "TG search"),
    ("tg_enrichment",        "TGe",    True,  "TG context"),
    ("tg_bot_tmux",          "Bot",    True,  "TG bot"),
    ("gate_auto_tune",       "Tune",   True,  "Auto-tune"),
    ("chain_memory",         "Chain",  True,  "Skill chain"),
    ("tg_session_notify",    "Notify", True,  "Session TG msg"),
    ("tg_mirror_messages",   "Mirror", True,  "All msgs→TG"),
    ("budget_degradation",   "Budget", True,  "4-tier deg"),
    ("session_token_budget", "TokBgt", False, "Token limit"),
]


class StatusView(Static):
    """Top 3 lines mirroring the statusline exactly."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def _health_color(self, pct):
        """Match statusline: cyan=100, green=90+, dark_orange=75+, yellow=50+, red=<50."""
        if pct >= 100:
            return "cyan"
        if pct >= 90:
            return "green"
        if pct >= 75:
            return "dark_orange"
        if pct >= 50:
            return "yellow"
        return "red"

    def _ctx_color(self, pct):
        """Match statusline: cyan<40, green=40-49, dark_orange=50-59, yellow=60-69, red=70+."""
        if pct >= 70:
            return "red"
        if pct >= 60:
            return "yellow"
        if pct >= 50:
            return "dark_orange"
        if pct >= 40:
            return "green"
        return "cyan"

    def render(self) -> str:
        import time as _t
        lines = []
        snap = self._data.statusline_snapshot()
        live = self._data.live_state()
        state = self._data.session_state()
        mem = self._data.memory_stats()

        # ── LINE 1: Identity ──
        model = snap.get("model", "?") if snap else "?"
        if model.startswith("claude-"):
            model = model[7:]
        m = model.split("-")[0].capitalize() if model else "?"
        ml = m.lower()
        mc = "dark_orange" if "opus" in ml else "dodger_blue" if "sonnet" in ml else "white" if "haiku" in ml else "cyan"

        s = live.get("session_count", "?")
        br = self._data.git_branch() or "?"
        mc_ = mem.get("mem_count", "?")
        tc = state.get("total_tool_calls", 0)
        fresh = self._data.memory_freshness()
        mode = self._data.active_mode()

        l1 = f"[{mc}]\\[{m}][/{mc}]"
        if mode:
            l1 += f" [bold cyan]MODE:{mode}[/bold cyan]"
        l1 += f" | \U0001f4c1 {live.get('project', 'torus')}"
        l1 += f" | \U0001f33f {br}"
        l1 += f" | [bold]#{s}[/bold]"
        l1 += f" | \U0001f6e1\ufe0f [cyan]G:{len(GATE_INFO)}[/cyan]"
        if fresh and fresh > 0:
            l1 += f" | \U0001f9e0 [cyan]M:{mc_}[/cyan] [green]\u2191{fresh}m[/green]"
        else:
            l1 += f" | \U0001f9e0 [cyan]M:{mc_}[/cyan]"
        l1 += f" | \u26a1[yellow]TC:{tc}[/yellow]"
        lines.append(l1)

        # ── LINE 2: Health + metrics ──
        health = snap.get("health_pct", 100) if snap else 100
        ctx = snap.get("context_pct", 0) if snap else 0
        cost = snap.get("cost_usd", 0) if snap else 0
        dur = snap.get("duration_min", 0) if snap else 0
        la = snap.get("lines_added", 0) if snap else 0
        lr = snap.get("lines_removed", 0) if snap else 0
        stok = snap.get("session_tokens", "0") if snap else "0"
        cmp = snap.get("compressions", 0) if snap else 0

        hc = self._health_color(health)
        filled = max(0, min(10, round(health / 10)))
        bar = f"[{hc}]HP:{'█' * filled}{'░' * (10 - filled)} {health}%[/{hc}]"

        cc = self._ctx_color(ctx)

        # Error velocity
        error_windows = state.get("error_windows", [])
        now = _t.time()
        recent_err = sum(
            e.get("count", 1) for e in error_windows
            if isinstance(e, dict) and now - e.get("last_seen", 0) < 300
        )
        total_err = sum(
            e.get("count", 1) for e in error_windows if isinstance(e, dict)
        )

        # Verification
        v_ok, v_total = self._data.verification_ratio()

        l2 = f"{bar} | [{cc}]\U0001f4e6{ctx}%[/{cc}]"
        if cmp:
            l2 += f" [yellow]CMP:{cmp}[/yellow]"
        if recent_err > 0:
            l2 += f" | [red]\u26a0\ufe0fE:{recent_err}\U0001f525[/red]"
        elif total_err > 0:
            l2 += f" | [yellow]\u26a0\ufe0fE:{total_err}[/yellow]"
        if stok and stok != "0":
            l2 += f" | [cyan]{stok} tok[/cyan]"
        if dur:
            l2 += f" | \u23f1\ufe0f {dur}m"
        if la or lr:
            l2 += f" | [green]+{la}[/green]/[red]-{lr}[/red]"
        if v_total > 0:
            vc = "green" if v_ok == v_total else "yellow"
            l2 += f" | [{vc}]\u2705V:{v_ok}/{v_total}[/{vc}]"
        cost_v = cost if isinstance(cost, (int, float)) else 0
        l2 += f" | \U0001f4b0[cyan]${cost_v:.2f}[/cyan]"
        lines.append(l2)

        return "\n".join(lines)


class GateView(Static):
    """Compact gate grid."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        eff = self._data.gate_effectiveness()
        lines = ["[dim]\u2500\u2500[/dim] \U0001f6e1\ufe0f [dim]GATES \u2500\u2500[/dim]"]
        for i in range(0, len(GATE_INFO), 2):
            left = self._gs(*GATE_INFO[i], eff)
            if i + 1 < len(GATE_INFO):
                right = self._gs(*GATE_INFO[i + 1], eff)
                lines.append(f"{left}  {right}")
            else:
                lines.append(left)
        return "\n".join(lines)

    def _gs(self, key, gid, name, gtype, eff):
        d = eff.get(key, {})
        b = d.get("blocks", 0)
        o = d.get("overrides", 0)
        t = b + o
        if t == 0:
            dot = "[dim]\u25cb[/dim]"
            stat = "[dim]  \u2014[/dim]"
        else:
            p = int(b / t * 100)
            dot = "[green]\u25cf[/green]" if p >= 90 else "[yellow]\u25cf[/yellow]" if p >= 70 else "[red]\u25cf[/red]"
            stat = f"{b:>3}"
        tb = "[red]B[/red]" if gtype == "B" else "[yellow]A[/yellow]"
        return f"{dot}{tb}[dim]{gid}[/dim] {name:<7} {stat}"


class AuditView(Static):
    """Recent audit entries."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        entries = self._data.audit_tail(12)
        lines = ["[dim]\u2500\u2500[/dim] \U0001f4dc [dim]AUDIT \u2500\u2500[/dim]"]
        if not entries:
            lines.append("[dim]no entries[/dim]")
        else:
            for e in entries[-8:]:
                dec = e.get("decision", "?")
                gate = e.get("gate", "")
                tool = e.get("tool", "?")[:6]
                ts = e.get("timestamp", "")
                tp = ts[11:16] if len(ts) >= 16 else ""

                gs = gate.split(": ", 1)[-1] if ": " in gate else gate
                ps = gs.split("_", 2)
                gs = ps[2][:7] if len(ps) == 3 and ps[0] == "gate" else gs[:7]

                icon = "[red]\u2715[/red]" if dec == "block" else "[yellow]\u26a0[/yellow]" if dec == "warn" else "[dim]\u00b7[/dim]"
                lines.append(f"{icon}[dim]{tp}[/dim] {gs:<7} {tool}")
        return "\n".join(lines)


class ToggleItem(Static):
    """A single clickable toggle line."""

    class Toggled(Message):
        def __init__(self, key: str, new_val):
            super().__init__()
            self.key = key
            self.new_val = new_val

    def __init__(self, key: str, label: str, is_bool: bool, desc: str, data: DataLayer):
        super().__init__(id=f"tog_{key}")
        self._key = key
        self._label = label
        self._is_bool = is_bool
        self._desc = desc
        self._data = data

    def render(self) -> str:
        live = self._data.live_state()
        v = live.get(self._key)
        if self._is_bool:
            icon = "\u2705" if v else "\U0001f518"
            return f"{icon}{self._label} [dim]{self._desc}[/dim]"
        else:
            return f"[cyan]{v or 0}[/cyan] {self._label} [dim]{self._desc}[/dim]"

    def on_click(self) -> None:
        live = self._data.live_state()
        v = live.get(self._key)
        if self._is_bool:
            new_val = not bool(v)
            self._data.set_toggle(self._key, new_val)
            self.post_message(self.Toggled(self._key, new_val))
        # Numeric toggles: click cycles 0 → 50k → 100k → 200k → 0
        else:
            cycle = [0, 50000, 100000, 200000]
            cur = int(v or 0)
            try:
                idx = cycle.index(cur)
                new_val = cycle[(idx + 1) % len(cycle)]
            except ValueError:
                new_val = 0
            self._data.set_toggle(self._key, new_val)
            self.post_message(self.Toggled(self._key, new_val))


class TorusApp(App):
    CSS = """
    Screen {
        background: #0c0c0c;
        overflow: hidden hidden;
    }
    StatusView {
        height: auto;
        padding: 0 0;
        color: #cccccc;
    }
    GateView {
        height: auto;
        padding: 0 0;
        color: #cccccc;
    }
    AuditView {
        height: auto;
        padding: 0 0;
        color: #cccccc;
    }
    ToggleItem {
        height: 1;
        padding: 0 0;
        color: #cccccc;
    }
    ToggleItem:hover {
        background: #1a1a2e;
    }
    .tog-hdr {
        height: 1;
        color: #666666;
        padding: 0 0;
    }
    Footer {
        background: #1a1a1a;
        height: 1;
        color: #666666;
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
        with VerticalScroll():
            yield StatusView(self.data)
            yield GateView(self.data)
            yield Static("[dim]\u2500\u2500 TOGGLES \u2500\u2500[/dim]", classes="tog-hdr")
            for key, label, is_bool, desc in TOGGLE_DISPLAY:
                yield ToggleItem(key, label, is_bool, desc, self.data)
            yield AuditView(self.data)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()
        for cls in (StatusView, GateView, AuditView):
            try:
                self.query_one(cls).refresh()
            except Exception:
                pass
        for key, _, _, _ in TOGGLE_DISPLAY:
            try:
                self.query_one(f"#tog_{key}").refresh()
            except Exception:
                pass

    @on(ToggleItem.Toggled)
    def on_toggle(self, event: ToggleItem.Toggled) -> None:
        self.notify(f"{event.key}: {event.new_val}", timeout=2)
        self._refresh()

    def action_refresh(self) -> None:
        self._refresh()

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.notify("PAUSED" if self.paused else "LIVE")


if __name__ == "__main__":
    if os.environ.get("CLAUDECODE"):
        print("ERROR: Do not run app.py from Claude's Bash tool — it will kill the session.")
        print("Use: bash ~/.claude/tui/launch.sh")
        sys.exit(1)
    TorusApp().run()
