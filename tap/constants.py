"""TAP constants and defaults."""

import os

SOCKET_PATH = os.environ.get("TAP_SOCKET", "/tmp/tap.sock")
HEARTBEAT_INTERVAL = 5  # seconds
HEARTBEAT_TIMEOUT = 10  # seconds before marking agent dead
DEFAULT_MODEL = "sonnet"
DEFAULT_PRIORITY = 5
MAX_AGENTS = 20
DEFAULT_ADAPTER = "claude"

# Agent states
STATE_READY = "ready"
STATE_IDLE = "idle"
STATE_WORKING = "working"
STATE_DEAD = "dead"

# Task stream event types
EVENT_TEXT = "text"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_PROGRESS = "progress"
