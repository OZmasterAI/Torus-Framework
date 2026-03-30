#!/usr/bin/env python3
"""
ASCII diagram generator for architecture visualization.
"""

from typing import List, Dict


def draw_component_tree(components: List[str], archetype: str) -> str:
    """Draw component hierarchy as ASCII tree."""
    lines = [
        "┌─────────────────────────────────────┐",
        "│         Main Model                  │",
        "├─────────────────────────────────────┤"
    ]

    # Add state fields
    lines.append("│  Components:                        │")
    for comp in components:
        lines.append(f"│   - {comp:<30} │")

    lines.append("└────────────┬───────────────┬────────┘")

    # Add component boxes below
    if len(components) >= 2:
        comp_boxes = []
        for comp in components[:3]:  # Show max 3
            comp_boxes.append(f"        ┌────▼────┐")
            comp_boxes.append(f"        │ {comp:<7} │")
            comp_boxes.append(f"        └─────────┘")
        return "\n".join(lines) + "\n" + "\n".join(comp_boxes)

    return "\n".join(lines)


def draw_message_flow(messages: List[str]) -> str:
    """Draw message flow diagram."""
    flow = ["Message Flow:"]
    flow.append("")
    flow.append("User Input → tea.KeyMsg → Update() →")
    for msg in messages:
        flow.append(f"  {msg} →")
    flow.append("  Model Updated → View() → Render")
    return "\n".join(flow)


def draw_state_machine(states: List[str]) -> str:
    """Draw state machine diagram."""
    if not states or len(states) < 2:
        return "Single-state application (no state machine)"

    diagram = ["State Machine:", ""]
    for i, state in enumerate(states):
        if i < len(states) - 1:
            diagram.append(f"{state} → {states[i+1]}")
        else:
            diagram.append(f"{state} → Done")

    return "\n".join(diagram)
