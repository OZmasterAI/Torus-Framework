#!/usr/bin/env python3
"""DAG-specific hook registry for conversation mutation events.

Lightweight, Python-side hook system that fires on DAG mutations.
Separate from Claude Code's hook system (settings.json) — these are
internal framework hooks for components that react to DAG changes.
"""

import sys

# Hook point constants
ON_NODE_ADDED = "on_node_added"
ON_BRANCH_SWITCH = "on_branch_switch"
ON_BRANCH_CREATED = "on_branch_created"
ON_BRANCH_RESET = "on_branch_reset"


class DAGHookRegistry:
    """Registry for DAG mutation event handlers."""

    def __init__(self):
        self._handlers = {}  # event -> [(priority, name, fn)]

    def register(self, event, fn, name="", priority=100):
        """Register a handler for a DAG event.

        Lower priority numbers run first (default 100).
        """
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append((priority, name, fn))
        self._handlers[event].sort(key=lambda x: x[0])

    def fire(self, event, data):
        """Fire all handlers for an event. Fail-open: exceptions logged, not raised."""
        handlers = self._handlers.get(event, [])
        for priority, name, fn in handlers:
            try:
                fn(data)
            except Exception as e:
                print(
                    f"[DAG hook] {event}/{name} failed: {e}",
                    file=sys.stderr,
                )

    def list_handlers(self, event=None):
        """List registered handlers, optionally filtered by event."""
        if event:
            return [(p, n) for p, n, _ in self._handlers.get(event, [])]
        return {
            ev: [(p, n) for p, n, _ in handlers]
            for ev, handlers in self._handlers.items()
        }
