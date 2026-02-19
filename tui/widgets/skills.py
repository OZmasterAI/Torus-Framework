"""Skill usage table."""

from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class SkillPanel(Widget):
    """Skill usage and recent invocations."""

    DEFAULT_CSS = """
    SkillPanel { height: auto; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="skill_content")

    def refresh_data(self, state: dict):
        usage = state.get("skill_usage", {})
        recent = state.get("recent_skills", [])

        lines = []
        if usage:
            lines.append("Skill usage:")
            for skill, count in sorted(usage.items(), key=lambda x: -x[1]):
                lines.append(f"  {skill}: {count}x")
        else:
            lines.append("No skills used this session")

        if recent:
            lines.append("")
            lines.append("Recent:")
            for s in recent[-5:]:
                lines.append(f"  {s}")

        self.query_one("#skill_content", Static).update("\n".join(lines))
