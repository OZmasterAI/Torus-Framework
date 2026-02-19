"""Gate effectiveness table with percentage bars."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable

# Maps effectiveness file keys to short display names
GATE_DISPLAY = {
    "gate_01_read_before_edit": "G 1 read_before",
    "gate_02_no_destroy": "G 2 no_destroy",
    "gate_03_test_before_deploy": "G 3 test_deploy",
    "gate_04_memory_first": "G 4 memory_first",
    "gate_05_proof_before_fixed": "G 5 proof_fixed",
    "gate_06_save_fix": "G 6 save_fix",
    "gate_07_critical_file_guard": "G 7 crit_guard",
    "gate_09_strategy_ban": "G 9 strat_ban",
    "gate_10_model_enforcement": "G10 model_cost",
    "gate_11_rate_limit": "G11 rate_limit",
    "gate_12_plan_mode_save": "G12 plan_save",
    "gate_13_workspace_isolation": "G13 workspace",
    "gate_14_confidence_check": "G14 confidence",
    "gate_15_causal_chain": "G15 causal",
    "gate_16_code_quality": "G16 quality",
}

# Canonical order
GATE_ORDER = [
    "gate_01_read_before_edit",
    "gate_02_no_destroy",
    "gate_03_test_before_deploy",
    "gate_04_memory_first",
    "gate_05_proof_before_fixed",
    "gate_06_save_fix",
    "gate_07_critical_file_guard",
    "gate_09_strategy_ban",
    "gate_10_model_enforcement",
    "gate_11_rate_limit",
    "gate_12_plan_mode_save",
    "gate_13_workspace_isolation",
    "gate_14_confidence_check",
    "gate_15_causal_chain",
    "gate_16_code_quality",
]


def _bar(pct: float, width: int = 8) -> str:
    filled = int(pct / 100 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


class GateTable(Widget):
    """Gate effectiveness as a DataTable."""

    DEFAULT_CSS = """
    GateTable { height: 1fr; }
    GateTable DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        table = DataTable(id="gate_table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table

    def on_mount(self):
        table = self.query_one("#gate_table", DataTable)
        table.add_columns("Gate", "Blk", "Ovr", "Pvt", "Eff", "Bar")

    def refresh_data(self, effectiveness: dict):
        table = self.query_one("#gate_table", DataTable)
        table.clear()

        for gate_key in GATE_ORDER:
            name = GATE_DISPLAY.get(gate_key, gate_key)
            data = effectiveness.get(gate_key, {})

            blocks = data.get("blocks", 0)
            overrides = data.get("overrides", 0)
            prevented = data.get("prevented", 0)
            total = blocks + overrides
            eff = int((blocks / total * 100) if total > 0 else 100)

            if blocks == 0 and overrides == 0:
                eff_str = "--"
                bar_str = "\u2591" * 8
            else:
                eff_str = f"{eff}%"
                bar_str = _bar(eff)

            table.add_row(name, str(blocks), str(overrides), str(prevented), eff_str, bar_str)
