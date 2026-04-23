"""TAP storage — thin wrapper around agent_channel.py for task persistence."""

from __future__ import annotations

import os
import sys
from typing import Any

# Add hooks to path so we can import shared.agent_channel
_hooks_dir = os.path.expanduser("~/.claude/hooks")
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)

from shared.agent_channel import (
    archive_tasks,
    cancel_stale,
    claim_next_task,
    cleanup,
    complete_task,
    create_task,
    get_task,
    list_tasks,
    post_message,
    read_messages,
    update_task,
)


class TAPStorage:
    """Task queue and messaging backed by agent_channel SQLite."""

    def dispatch(
        self,
        agent_id: str,
        title: str,
        description: str = "",
        priority: int = 5,
        depends_on: str | None = None,
    ) -> str | None:
        """Create and assign a task to a specific agent. Returns task_id."""
        return create_task(
            title=title,
            description=description,
            created_by="tap",
            assigned_to=agent_id,
            required_role=agent_id,
            priority=priority,
            depends_on=depends_on,
            notify=True,
        )

    def dispatch_to_role(
        self,
        role: str,
        title: str,
        description: str = "",
        priority: int = 5,
    ) -> str | None:
        """Create a task for any agent with a given role. Returns task_id."""
        return create_task(
            title=title,
            description=description,
            created_by="tap",
            required_role=role,
            priority=priority,
            notify=False,
        )

    def complete(self, task_id: str, result: str = "") -> bool:
        """Mark a task as done."""
        return complete_task(task_id, result, broadcast=True)

    def fail(self, task_id: str, error: str = "") -> bool:
        """Mark a task as failed."""
        return update_task(task_id, "failed", result=error)

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Get a task by ID."""
        return get_task(task_id)

    def pending(self, role: str | None = None) -> list[dict[str, Any]]:
        """List pending tasks, optionally filtered by role."""
        tasks = list_tasks(status="pending")
        if role:
            tasks = [
                t
                for t in tasks
                if t.get("required_role") is None or t.get("required_role") == role
            ]
        return tasks

    def claim(self, agent_id: str, role: str | None = None) -> dict[str, Any] | None:
        """Atomically claim the next available task."""
        return claim_next_task(agent_id, role=role)

    def broadcast(self, from_agent: str, message: str) -> bool:
        """Broadcast a message to all agents."""
        return post_message(from_agent, "broadcast", message)

    def read(self, agent_id: str, since: float = 0.0) -> list[dict[str, Any]]:
        """Read messages for an agent since timestamp."""
        return read_messages(since, agent_id=agent_id)

    def cancel_stale_tasks(self, timeout_s: int = 300) -> int:
        """Cancel tasks stuck in assigned/running state."""
        return cancel_stale(timeout_s)

    def archive(self, older_than_hours: int = 48) -> int:
        """Archive completed/failed tasks."""
        return archive_tasks(older_than_hours)
