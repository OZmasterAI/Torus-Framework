"""Gate effectiveness table with colored percentage bars."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable
from rich.text import Text

# Maps effectiveness file keys to display info: (id, name, type)
GATE_INFO = [
    ("gate_01_read_before_edit",    "G1",  "Read Before Edit",     "Blocking"),
    ("gate_02_no_destroy",          "G2",  "No Destroy",           "Blocking"),
    ("gate_03_test_before_deploy",  "G3",  "Test Before Deploy",   "Blocking"),
    ("gate_04_memory_first",        "G4",  "Memory First",         "Blocking"),
    ("gate_05_proof_before_fixed",  "G5",  "Proof Before Fixed",   "Blocking"),
    ("gate_06_save_fix",            "G6",  "Save Verified Fix",    "Advisory"),
    ("gate_07_critical_file_guard", "G7",  "Critical File Guard",  "Blocking"),
    ("gate_09_strategy_ban",        "G9",  "Strategy Ban",         "Blocking"),
    ("gate_10_model_enforcement",   "G10", "Model Cost Guard",     "Blocking"),
    ("gate_11_rate_limit",          "G11", "Rate Limit",           "Blocking"),
    ("gate_12_plan_mode_save",      "G12", "Plan Mode Save",       "Advisory"),
    ("gate_13_workspace_isolation", "G13", "Workspace Isolation",  "Blocking"),
    ("gate_14_confidence_check",    "G14", "Confidence Check",     "Blocking"),
    ("gate_15_causal_chain",        "G15", "Causal Chain",         "Blocking"),
    ("gate_16_code_quality",        "G16", "Code Quality",         "Blocking"),
]


def _colored_bar(pct: int) -> Text:
    """Create a colored bar: green >= 90, yellow >= 75, red below."""
    filled = pct // 10
    color = "green" if pct >= 90 else "yellow" if pct >= 75 else "red"
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    return Text(f"{bar} {pct}%", style=color)


class GateTable(Widget):
    """Gate effectiveness as a DataTable with colored bars."""

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
        table.add_columns("ID", "Gate Name", "Type", "Effectiveness", "Actions")

    def refresh_data(self, effectiveness: dict):
        table = self.query_one("#gate_table", DataTable)
        table.clear()

        for gate_key, gid, name, gtype in GATE_INFO:
            data = effectiveness.get(gate_key, {})

            blocks = data.get("blocks", 0)
            overrides = data.get("overrides", 0)
            prevented = data.get("prevented", 0)
            total = blocks + overrides
            eff = int((blocks / total * 100) if total > 0 else 100)

            type_text = (
                Text(gtype, style="bold red")
                if gtype == "Blocking"
                else Text(gtype, style="yellow")
            )

            if blocks == 0 and overrides == 0:
                eff_bar = Text("\u2591" * 10 + " --", style="dim")
                actions = "no data"
            else:
                eff_bar = _colored_bar(eff)
                actions = f"{blocks} blocked"

            table.add_row(gid, name, type_text, eff_bar, actions)
