#!/usr/bin/env python3
"""Enforcer Shim — fast path via daemon socket, fallback to inline.

This replaces enforcer.py as the PreToolUse hook entry point.

Fast path (~43ms): Python startup (37ms) + socket round-trip (~5ms)
Slow path (~134ms): Python startup (37ms) + import enforcer + main() (~97ms)

The slow path is identical to the previous direct enforcer.py invocation,
so there's zero downside if the daemon isn't running.
"""

import json
import os
import socket
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
SOCKET_PATH = os.path.join(HOOKS_DIR, ".enforcer.sock")


def _try_daemon(raw_input: bytes) -> bool:
    """Try to send request to daemon via UDS. Returns True if handled."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(4)  # Under the 5s hook timeout
        sock.connect(SOCKET_PATH)

        # Send request (JSON-over-newline protocol)
        sock.sendall(raw_input + b"\n")

        # Read response
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        sock.close()

        if not buf:
            return False

        resp = json.loads(buf.decode("utf-8").strip())
        exit_code = resp.get("exit_code", 0)
        stderr_text = resp.get("stderr", "")
        stdout_text = resp.get("stdout", "")

        if stderr_text:
            sys.stderr.write(stderr_text)
        if stdout_text:
            sys.stdout.write(stdout_text)

        sys.exit(exit_code)

    except (ConnectionRefusedError, FileNotFoundError, BrokenPipeError,
            socket.timeout, json.JSONDecodeError, OSError):
        return False


def _run_inline(raw_input: bytes):
    """Fallback: import enforcer and run main() in-process."""
    import io
    sys.path.insert(0, HOOKS_DIR)
    import enforcer
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw_input))
    enforcer.main()


def main():
    raw = sys.stdin.buffer.read()

    # Fast path: try daemon socket
    if os.path.exists(SOCKET_PATH):
        if _try_daemon(raw):
            return  # Handled (won't reach here — _try_daemon calls sys.exit)

    # Slow path: inline execution (same as calling enforcer.py directly)
    _run_inline(raw)


if __name__ == "__main__":
    main()
