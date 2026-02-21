"""Lightweight pub/sub event bus for inter-component communication.

Provides a process-local event bus with ramdisk persistence for the Torus
self-healing framework. Designed for hook and gate coordination.

Design constraints:
- Fail-open: publish() never raises; all exceptions are swallowed.
- Ring buffer: in-memory log capped at max_events (default 1000), oldest dropped.
- Ramdisk persistence: /dev/shm/claude-hooks/events.json (fast, ephemeral).
- Fallback: ~/.claude/hooks/.events_cache.json (disk, if /dev/shm unavailable).
- Thread-safe: _lock protects all shared state mutations.

Built-in event types:
    GATE_FIRED       A gate was evaluated (any decision)
    GATE_BLOCKED     A gate issued a block decision
    MEMORY_QUERIED   A memory search was performed
    TEST_RUN         A test suite was executed
    ERROR_DETECTED   An error was detected by a gate or hook
    FIX_APPLIED      A causal-chain fix was applied
    TOOL_CALLED      A tool was invoked (PreToolUse)

Usage:
    from shared.event_bus import subscribe, publish, get_recent, get_stats

    subscribe(EventType.GATE_BLOCKED, lambda data: print("blocked!", data))
    publish(EventType.GATE_FIRED, {"gate": "Gate 1", "tool": "Edit"})
    recent = get_recent(EventType.GATE_BLOCKED, limit=10)
    stats = get_stats()
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

# ── Path constants ─────────────────────────────────────────────────────────────

EVENTS_RAMDISK_DIR = "/dev/shm/claude-hooks"
EVENTS_RAMDISK_PATH = os.path.join(EVENTS_RAMDISK_DIR, "events.json")
EVENTS_DISK_FALLBACK = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".events_cache.json"
)

# ── Built-in event types ───────────────────────────────────────────────────────


class EventType:
    """Namespace for built-in event type string constants."""
    GATE_FIRED      = "GATE_FIRED"
    GATE_BLOCKED    = "GATE_BLOCKED"
    MEMORY_QUERIED  = "MEMORY_QUERIED"
    TEST_RUN        = "TEST_RUN"
    ERROR_DETECTED  = "ERROR_DETECTED"
    FIX_APPLIED     = "FIX_APPLIED"
    TOOL_CALLED     = "TOOL_CALLED"

    ALL = (
        GATE_FIRED,
        GATE_BLOCKED,
        MEMORY_QUERIED,
        TEST_RUN,
        ERROR_DETECTED,
        FIX_APPLIED,
        TOOL_CALLED,
    )


# ── Internal bus state ────────────────────────────────────────────────────────

_DEFAULT_MAX_EVENTS = 1000

_lock: threading.Lock = threading.Lock()
_subscribers: Dict[str, List[Callable]] = {}   # event_type -> [handler, ...]
_event_log: deque = deque(maxlen=_DEFAULT_MAX_EVENTS)

# Per-event-type publish counters (never reset, for get_stats())
_publish_counts: Dict[str, int] = {}
_block_counts: Dict[str, int] = {}  # handler exception tallies
_total_published: int = 0


def configure(max_events: int = _DEFAULT_MAX_EVENTS) -> None:
    """Reconfigure the ring buffer capacity.

    Creates a new deque with the given maxlen, preserving existing events
    (up to the new limit, keeping the most recent).

    Args:
        max_events: Maximum number of events to keep in memory (default 1000).
    """
    global _event_log
    with _lock:
        new_log: deque = deque(_event_log, maxlen=max_events)
        _event_log = new_log


# ── Core API ──────────────────────────────────────────────────────────────────


def subscribe(event_type: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callback for a specific event type.

    The handler will be called synchronously in the publish() call.
    Handler exceptions are caught and never propagate.

    Args:
        event_type: One of EventType.* or any custom string.
        handler: Callable that accepts a single dict (the event payload).
    """
    with _lock:
        if event_type not in _subscribers:
            _subscribers[event_type] = []
        if handler not in _subscribers[event_type]:
            _subscribers[event_type].append(handler)


def unsubscribe(event_type: str, handler: Callable) -> bool:
    """Remove a previously registered handler.

    Args:
        event_type: The event type the handler was registered for.
        handler: The exact callable object to remove.

    Returns:
        True if the handler was found and removed, False otherwise.
    """
    with _lock:
        handlers = _subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            return True
        return False


def publish(
    event_type: str,
    data: Any = None,
    source: str = "",
    persist: bool = True,
) -> Optional[Dict[str, Any]]:
    """Emit an event to all registered handlers and append to the event log.

    Never raises. All handler exceptions and I/O errors are swallowed.

    Args:
        event_type: Event type string (e.g. EventType.GATE_FIRED).
        data: Arbitrary event payload (must be JSON-serialisable for persistence).
        source: Optional identifier for the publishing component.
        persist: If True (default), flush the event log to ramdisk.

    Returns:
        The event dict that was published, or None on catastrophic failure.
    """
    global _total_published

    try:
        event: Dict[str, Any] = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
            "source": source,
        }

        # Append to ring buffer and update counters under lock
        with _lock:
            _event_log.append(event)
            _publish_counts[event_type] = _publish_counts.get(event_type, 0) + 1
            _total_published += 1
            # Snapshot handlers under lock to avoid mutation during iteration
            handlers = list(_subscribers.get(event_type, []))

        # Call handlers outside the lock (avoid deadlock if handler calls publish)
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                with _lock:
                    _block_counts[event_type] = _block_counts.get(event_type, 0) + 1

        # Persist to ramdisk (outside lock; atomic-replace is safe)
        if persist:
            _persist_events()

        return event

    except Exception:
        return None


def get_recent(
    event_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return the most recent events from the ring buffer.

    Args:
        event_type: If given, filter to only this event type. None = all types.
        limit: Maximum number of events to return (most recent first).

    Returns:
        List of event dicts, most recent last (chronological order).
    """
    with _lock:
        snapshot = list(_event_log)

    if event_type is not None:
        snapshot = [e for e in snapshot if e.get("type") == event_type]

    # Return up to `limit` most recent (tail of the list)
    return snapshot[-limit:] if len(snapshot) > limit else snapshot


def clear() -> None:
    """Clear the in-memory event log and subscriber registry.

    Also removes the persisted events file if it exists.
    Intended for testing and session resets.
    """
    global _total_published
    with _lock:
        _event_log.clear()
        _subscribers.clear()
        _publish_counts.clear()
        _block_counts.clear()
        _total_published = 0

    # Remove persisted file (fail silently)
    _remove_events_file()


def get_stats() -> Dict[str, Any]:
    """Return aggregate statistics about the event bus.

    Returns:
        Dict with keys:
            total_published (int): All events ever published this process.
            events_in_buffer (int): Current ring buffer occupancy.
            buffer_capacity (int): Maximum ring buffer size.
            subscriber_count (int): Total registered handlers across all types.
            by_type (dict): Per-type publish counts.
            handler_errors (dict): Per-type handler exception counts.
    """
    with _lock:
        return {
            "total_published":  _total_published,
            "events_in_buffer": len(_event_log),
            "buffer_capacity":  _event_log.maxlen,
            "subscriber_count": sum(len(v) for v in _subscribers.values()),
            "by_type":          dict(_publish_counts),
            "handler_errors":   dict(_block_counts),
        }


# ── Persistence helpers ────────────────────────────────────────────────────────


def _events_path() -> str:
    """Return the active persistence path (ramdisk or fallback)."""
    if os.path.isdir(EVENTS_RAMDISK_DIR):
        return EVENTS_RAMDISK_PATH
    return EVENTS_DISK_FALLBACK


def _persist_events() -> None:
    """Flush the current event log snapshot to a JSON file.

    Uses an atomic write (tmp-then-rename) to prevent corruption.
    Completely fail-open: any exception is silently discarded.
    """
    try:
        path = _events_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with _lock:
            snapshot = list(_event_log)

        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(snapshot, fh, default=str)
        os.replace(tmp_path, path)
    except Exception:
        pass


def _remove_events_file() -> None:
    """Remove the persisted events file. Fail-open."""
    try:
        path = _events_path()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def load_persisted() -> List[Dict[str, Any]]:
    """Load events from the persisted JSON file into the ring buffer.

    Useful for reading events from a previous hook invocation in the same
    session (since each hook invocation is a separate process).

    Returns:
        Number of events loaded.
    """
    try:
        path = _events_path()
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            events = json.load(fh)
        if not isinstance(events, list):
            return []
        with _lock:
            for event in events:
                if isinstance(event, dict):
                    _event_log.append(event)
        return events
    except Exception:
        return []


# ── __main__ smoke test ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _PASS = 0
    _FAIL = 0

    def _assert(name: str, condition: bool, detail: str = "") -> None:
        global _PASS, _FAIL
        if condition:
            _PASS += 1
            print(f"  PASS  {name}")
        else:
            _FAIL += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    print("event_bus.py — smoke test\n")

    # ── Reset state before tests ─────────────────────────────────────────────
    clear()

    # 1. EventType constants exist
    _assert(
        "EventType constants defined",
        all(hasattr(EventType, t) for t in (
            "GATE_FIRED", "GATE_BLOCKED", "MEMORY_QUERIED",
            "TEST_RUN", "ERROR_DETECTED", "FIX_APPLIED", "TOOL_CALLED",
        )),
    )

    # 2. publish returns an event dict
    evt = publish(EventType.GATE_FIRED, {"gate": "Gate 1", "tool": "Edit"}, source="test")
    _assert(
        "publish returns event dict",
        isinstance(evt, dict) and evt["type"] == EventType.GATE_FIRED,
        f"got {evt}",
    )

    # 3. get_recent returns published event
    recent = get_recent()
    _assert(
        "get_recent returns published event",
        len(recent) == 1 and recent[0]["type"] == EventType.GATE_FIRED,
        f"got {recent}",
    )

    # 4. subscribe and handler called on publish
    received: List[Dict] = []
    subscribe(EventType.GATE_BLOCKED, lambda e: received.append(e))
    publish(EventType.GATE_BLOCKED, {"gate": "Gate 2"}, source="test")
    _assert(
        "subscribe handler is called",
        len(received) == 1 and received[0]["data"]["gate"] == "Gate 2",
        f"received={received}",
    )

    # 5. get_recent with event_type filter
    only_blocked = get_recent(EventType.GATE_BLOCKED)
    _assert(
        "get_recent filters by event_type",
        all(e["type"] == EventType.GATE_BLOCKED for e in only_blocked),
        f"got {only_blocked}",
    )

    # 6. get_stats returns correct counts
    publish(EventType.TOOL_CALLED, {"tool": "Bash"}, source="test")
    stats = get_stats()
    _assert(
        "get_stats total_published correct",
        stats["total_published"] == 3,
        f"total_published={stats['total_published']}",
    )
    _assert(
        "get_stats by_type correct",
        stats["by_type"].get(EventType.GATE_FIRED) == 1
        and stats["by_type"].get(EventType.GATE_BLOCKED) == 1
        and stats["by_type"].get(EventType.TOOL_CALLED) == 1,
        f"by_type={stats['by_type']}",
    )

    # 7. configure ring buffer capacity
    configure(max_events=5)
    for i in range(10):
        publish(EventType.TEST_RUN, {"run": i}, persist=False)
    buf_events = get_recent()
    _assert(
        "configure ring buffer caps at new max_events",
        len(buf_events) <= 5,
        f"len={len(buf_events)}",
    )
    # Restore default capacity
    configure(max_events=_DEFAULT_MAX_EVENTS)

    # 8. publish never raises even with a broken handler
    def _bad_handler(e: Dict) -> None:
        raise RuntimeError("intentional handler failure")

    clear()
    subscribe(EventType.ERROR_DETECTED, _bad_handler)
    result = publish(EventType.ERROR_DETECTED, {"msg": "oops"})
    _assert(
        "publish survives broken handler (fail-open)",
        result is not None and result["type"] == EventType.ERROR_DETECTED,
        f"result={result}",
    )

    # 9. unsubscribe removes handler
    received2: List[Dict] = []
    handler2 = lambda e: received2.append(e)
    subscribe(EventType.FIX_APPLIED, handler2)
    unsubscribe(EventType.FIX_APPLIED, handler2)
    publish(EventType.FIX_APPLIED, {"fix": "patch-1"})
    _assert(
        "unsubscribe prevents handler from being called",
        len(received2) == 0,
        f"received2={received2}",
    )

    # 10. clear() resets bus entirely
    clear()
    stats_after_clear = get_stats()
    _assert(
        "clear() resets all counters and log",
        stats_after_clear["total_published"] == 0
        and stats_after_clear["events_in_buffer"] == 0
        and stats_after_clear["subscriber_count"] == 0,
        f"stats={stats_after_clear}",
    )

    # 11. ramdisk persistence round-trip
    clear()
    publish(EventType.MEMORY_QUERIED, {"query": "event bus"}, source="test")
    # Read back raw file
    path = _events_path()
    persisted_ok = False
    try:
        with open(path) as fh:
            raw = json.load(fh)
        persisted_ok = (
            isinstance(raw, list)
            and len(raw) == 1
            and raw[0]["type"] == EventType.MEMORY_QUERIED
        )
    except Exception as exc:
        persisted_ok = False
        print(f"    [debug] persistence read error: {exc}")
    _assert(
        "events persisted to ramdisk/fallback path",
        persisted_ok,
        f"path={path}",
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\nResults: {_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)
