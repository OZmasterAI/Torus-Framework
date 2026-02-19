"""Toggle panel - 8 boolean switches + budget input."""

from textual.app import ComposeResult
from textual.widgets import Static, Switch, Input, Label
from textual.widget import Widget
from textual.message import Message


class ToggleRow(Widget):
    """A single toggle: label + switch."""

    DEFAULT_CSS = """
    ToggleRow {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    ToggleRow Label {
        width: 1fr;
    }
    ToggleRow Switch {
        width: auto;
    }
    """

    class Changed(Message):
        def __init__(self, key: str, value: bool):
            super().__init__()
            self.key = key
            self.value = value

    def __init__(self, label: str, key: str, value: bool = False):
        super().__init__()
        self.label_text = label
        self.key = key
        self.initial_value = value

    def compose(self) -> ComposeResult:
        yield Label(self.label_text)
        yield Switch(value=self.initial_value, id=f"sw_{self.key}")

    def on_switch_changed(self, event: Switch.Changed):
        self.post_message(self.Changed(self.key, event.value))


class BudgetRow(Widget):
    """Budget input row."""

    DEFAULT_CSS = """
    BudgetRow {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    BudgetRow Label {
        width: 1fr;
    }
    BudgetRow Input {
        width: 12;
    }
    """

    class Changed(Message):
        def __init__(self, value: int):
            super().__init__()
            self.value = value

    def __init__(self, value: int = 0):
        super().__init__()
        self.initial_value = value

    def compose(self) -> ComposeResult:
        yield Label("Token budget")
        yield Input(str(self.initial_value), id="budget_input", type="integer")

    def on_input_submitted(self, event: Input.Submitted):
        try:
            val = int(event.value)
        except ValueError:
            val = 0
        self.post_message(self.Changed(val))


class TogglePanel(Widget):
    """All toggles in a vertical panel."""

    DEFAULT_CSS = """
    TogglePanel {
        height: auto;
        border: solid $primary;
        padding: 0;
    }
    """

    def __init__(self, toggles: list, live_state: dict, **kwargs):
        super().__init__(**kwargs)
        self.toggles = toggles
        self.live_state = live_state

    def compose(self) -> ComposeResult:
        yield Static(" Toggles", classes="panel-title")
        for label, key, default, desc in self.toggles:
            val = self.live_state.get(key, default)
            yield ToggleRow(label, key, val)
        budget = self.live_state.get("session_token_budget", 0)
        yield BudgetRow(budget)

    def refresh_data(self, live_state: dict):
        self.live_state = live_state
        for label, key, default, desc in self.toggles:
            val = live_state.get(key, default)
            try:
                sw = self.query_one(f"#sw_{key}", Switch)
                if sw.value != val:
                    sw.value = val
            except Exception:
                pass
