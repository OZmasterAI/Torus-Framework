"""Mock adapter for testing — wraps a simple echo subprocess."""

from __future__ import annotations

import sys

from .base import BaseAdapter

# Python script that echoes stdin lines back with prefix
_ECHO_SCRIPT = (
    "import sys\n"
    "for line in sys.stdin:\n"
    "    line = line.strip()\n"
    "    if not line:\n"
    "        continue\n"
    "    print(f'result: {line}', flush=True)\n"
)


class MockAdapter(BaseAdapter):
    """Test adapter using a Python echo subprocess."""

    def __init__(self, model: str = "mock", persistent: bool = True):
        super().__init__(model=model, persistent=persistent)

    def spawn_cmd(self) -> list[str]:
        return [sys.executable, "-c", _ECHO_SCRIPT]
