#!/usr/bin/env python3
"""Torus Framework — Terminal Dashboard (Textual)

Mirrors the statusline's terminal aesthetic: pipe-delimited, emoji-tagged,
compact text. Refreshes every 2s from the same data sources.

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

from data import DataLayer

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
    ("gate_17_injection_defense",   "17", "InjDefense",  "B"),
]


class TerminalView(Static):
    """Single widget that renders the entire dashboard as terminal text."""

    def __init__(self, data: DataLayer):
        super().__init__()
        self._data = data

    def render(self) -> str:
        lines = []
        snap = self._data.statusline_snapshot()
        live = self._data.live_state()
        state = self._data.session_state()
        mem = self._data.memory_stats()
        eff = self._data.gate_effectiveness()

        # ── LINE 1: Identity ──
        model = snap.get("model", "Claude") if snap else "Claude"
        if model.startswith("claude-"):
            model = model[7:]
        model_upper = model.split("-")[0].capitalize() if model else "Claude"

        # Color model name
        ml = model_upper.lower()
        if "opus" in ml:
            mc = "dark_orange"
        elif "sonnet" in ml:
            mc = "dodger_blue"
        elif "haiku" in ml:
            mc = "white"
        else:
            mc = "cyan"

        session = live.get("session_count", "?")
        branch = self._data.git_branch() or "?"
        mem_count = mem.get("mem_count", "?")
        gate_count = len(GATE_INFO)
        total_calls = state.get("total_tool_calls", 0)
        mode = self._data.active_mode()

        l1 = f"[{mc}]\\[{model_upper}][/{mc}]"
        if mode:
            l1 += f" MODE:{mode}"
        l1 += f" | \U0001f4c1 {live.get('project', 'torus')}"
        l1 += f" | \U0001f33f {branch}"
        l1 += f" | #{session}"
        l1 += f" | \U0001f6e1\ufe0f G:{gate_count}"
        # Memory + freshness
        fresh = self._data.memory_freshness()
        if fresh is not None and fresh > 0:
            l1 += f" | \U0001f9e0 M:{mem_count} \u2191{fresh}m"
        else:
            l1 += f" | \U0001f9e0 M:{mem_count}"
        l1 += f" | \u26a1TC:{total_calls}"
        lines.append(l1)

        # ── LINE 2: Health + context + metrics ──
        health = snap.get("health_pct", 100) if snap else 100
        ctx = snap.get("context_pct", 0) if snap else 0
        cost = snap.get("cost_usd", 0) if snap else 0
        dur = snap.get("duration_min", 0) if snap else 0
        la = snap.get("lines_added", 0) if snap else 0
        lr = snap.get("lines_removed", 0) if snap else 0
        stok = snap.get("session_tokens", "0") if snap else "0"
        lturn = snap.get("last_turn", "") if snap else ""
        cmp = snap.get("compressions", 0) if snap else 0

        # Health bar (10-char)
        filled = health // 10
        if health >= 80:
            hc = "green"
        elif health >= 50:
            hc = "yellow"
        else:
            hc = "red"
        bar = f"[{hc}]{'█' * filled}{'░' * (10 - filled)}[/{hc}] {health}%"

        # Context %
        if ctx >= 70:
            cc = "red"
        elif ctx >= 50:
            cc = "yellow"
        else:
            cc = "green"
        ctx_str = f"[{cc}]{ctx}%[/{cc}]"
        if cmp > 0:
            ctx_str = f"\U0001f4e6{ctx_str} CMP:{cmp}"

        l2_parts = [bar, ctx_str]

        # Error velocity
        error_windows = state.get("error_windows", [])
        now = time.time()
        recent_err = sum(
            e.get("count", 1) for e in error_windows
            if isinstance(e, dict) and now - e.get("last_seen", 0) < 300
        )
        if recent_err > 0:
            l2_parts.append(f"[red]E:{recent_err}\U0001f525[/red]")

        # Tokens
        if stok and stok != "0":
            tok_str = f"{stok} tok"
            if lturn:
                tok_str += f" ({lturn})"
            l2_parts.append(tok_str)

        if dur:
            l2_parts.append(f"\u23f1\ufe0f {dur}m")
        if la or lr:
            l2_parts.append(f"+{la}/-{lr}")

        # Verification
        v_ok, v_total = self._data.verification_ratio()
        if v_total > 0:
            l2_parts.append(f"\u2705V:{v_ok}/{v_total}")

        if isinstance(cost, (int, float)) and cost > 0:
            l2_parts.append(f"\U0001f4b0${cost:.2f}")
        else:
            l2_parts.append("\U0001f4b0$0.00")

        lines.append(" | ".join(l2_parts))

        # ── LINE 3: Toggles ──
        def tog(key):
            v = live.get(key)
            return "\u2705" if v else "\U0001f518"

        budget_val = live.get("session_token_budget", 0) or 0
        budget_tier = ""
        if live.get("budget_degradation") and budget_val > 0:
            tier = state.get("budget_tier", "normal")
            tier_map = {"dead": " \u2620\ufe0fDEAD", "critical": " \U0001f534CRIT", "low_compute": " \U0001f7e1LOW"}
            budget_tier = tier_map.get(tier, "")

        l3 = (
            f"{tog('terminal_l2_always')}L2 "
            f"{tog('context_enrichment')}Enrich "
            f"{tog('tg_l3_always')}TG "
            f"{tog('tg_enrichment')}TGe "
            f"{tog('tg_bot_tmux')}Bot "
            f"{tog('gate_auto_tune')}Tune "
            f"{tog('budget_degradation')}Budget "
            f"{tog('chain_memory')}Chain "
            f"B:{budget_val}{budget_tier}"
        )
        lines.append(l3)

        # ── SEPARATOR ──
        lines.append("[dim]" + "\u2500" * 50 + "[/dim]")

        # ── GATES ──
        lines.append("[bold]\U0001f6e1\ufe0f GATES[/bold]")
        for i in range(0, len(GATE_INFO), 2):
            left = self._gate_str(*GATE_INFO[i], eff)
            if i + 1 < len(GATE_INFO):
                right = self._gate_str(*GATE_INFO[i + 1], eff)
                lines.append(f" {left}  {right}")
            else:
                lines.append(f" {left}")

        # ── SEPARATOR ──
        lines.append("[dim]" + "\u2500" * 50 + "[/dim]")

        # ── AUDIT ──
        lines.append("[bold]\U0001f4dc AUDIT[/bold]")
        entries = self._data.audit_tail(12)
        if not entries:
            lines.append(" [dim]no entries today[/dim]")
        else:
            for entry in entries[-10:]:
                decision = entry.get("decision", "?")
                gate = entry.get("gate", "")
                tool = entry.get("tool", "?")
                ts = entry.get("timestamp", "")
                tp = ts[11:16] if len(ts) >= 16 else "     "

                # Shorten gate
                gs = gate.split(": ", 1)[-1] if ": " in gate else gate
                parts_g = gs.split("_", 2)
                if len(parts_g) == 3 and parts_g[0] == "gate":
                    gs = parts_g[2][:9]
                else:
                    gs = gs[:9]

                tool_short = tool[:8]

                if decision == "block":
                    icon = "[red]\u2715[/red]"
                elif decision == "warn":
                    icon = "[yellow]\u26a0[/yellow]"
                else:
                    icon = "[dim]\u00b7[/dim]"

                lines.append(f" {icon} [dim]{tp}[/dim] {gs:<9} {tool_short}")

        return "\n".join(lines)

    def _gate_str(self, key, gid, name, gtype, eff):
        d = eff.get(key, {})
        blocks = d.get("blocks", 0)
        overrides = d.get("overrides", 0)
        total = blocks + overrides

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

        t_badge = "[red]B[/red]" if gtype == "B" else "[yellow]A[/yellow]"
        return f"{dot}{t_badge}[dim]{gid}[/dim] {name:<10}{stat}"


class TorusApp(App):
    CSS = """
    Screen {
        background: #0c0c0c;
        overflow: hidden hidden;
    }

    TerminalView {
        height: auto;
        padding: 0 1;
        color: #cccccc;
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
            yield TerminalView(self.data)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh)

    def _refresh(self):
        if self.paused:
            return
        self.data.invalidate()
        try:
            self.query_one(TerminalView).refresh()
        except Exception:
            pass

    def action_refresh(self) -> None:
        self._refresh()
        self.notify("Refreshed", timeout=1)

    def action_toggle_pause(self):
        self.paused = not self.paused
        self.notify("PAUSED" if self.paused else "LIVE")


if __name__ == "__main__":
    TorusApp().run()
