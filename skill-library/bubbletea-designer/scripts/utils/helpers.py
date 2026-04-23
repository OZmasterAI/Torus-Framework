#!/usr/bin/env python3
"""
General helper utilities for Bubble Tea Designer.
"""

from datetime import datetime
from typing import Optional


def get_timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().isoformat()


def format_list_markdown(items: list, ordered: bool = False) -> str:
    """Format list as markdown."""
    if not items:
        return ""

    if ordered:
        return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    else:
        return "\n".join(f"- {item}" for item in items)


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."


def estimate_complexity(num_components: int, num_views: int = 1) -> str:
    """Estimate implementation complexity."""
    if num_components <= 2 and num_views == 1:
        return "Simple (1-2 hours)"
    elif num_components <= 4 and num_views <= 2:
        return "Medium (2-4 hours)"
    else:
        return "Complex (4+ hours)"
