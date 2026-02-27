#!/usr/bin/env python3
"""Enforcer Daemon — persistent UDS server for fast gate checking.

Eliminates Python startup + import cost (~97ms) for gated tool calls by
keeping the enforcer loaded in a long-running process. The enforcer_shim.py
connects to .enforcer.sock and gets responses in ~5ms instead of ~134ms.

Protocol (JSON-over-newline, same as memory_server.py):
  Request:  raw Claude Code hook JSON (same as stdin to enforcer.py)
  Response: {"exit_code": 0|2, "stderr": "...", "stdout": "..."}

If this daemon isn't running, the shim falls back to inline enforcer.main()
— zero downside risk.

Started by: boot_pkg/orchestrator.py (when config.json enforcer_daemon=true)
Stopped by: session_end.py (SIGTERM to PID file)
"""

import atexit
import io
import json
import os
import signal
import socket
import sys
import threading
import time

# Add hooks dir to path for enforcer imports
HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS_DIR)

SOCKET_PATH = os.path.join(HOOKS_DIR, ".enforcer.sock")
PID_FILE = os.path.join(HOOKS_DIR, ".enforcer.pid")

_server_socket = None
_lock = threading.Lock()


def _run_enforcer(request_json: str) -> dict:
    """Run enforcer.main() with captured stdio and exit code.

    Serialized by _lock to prevent concurrent stdio redirect conflicts.
    Returns {"exit_code": int, "stderr": str, "stdout": str}.
    """
    import enforcer  # Already loaded — no import cost after first call

    with _lock:
        # Save originals
        orig_stdin = sys.stdin
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        # Replace with buffers
        sys.stdin = io.TextIOWrapper(io.BytesIO(request_json.encode("utf-8")))
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr

        exit_code = 0
        try:
            enforcer.main()
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            captured_stderr.write(f"[DAEMON] Enforcer crash: {e}\n")
            exit_code = 2  # Fail-closed on unexpected errors
        finally:
            # Restore originals
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr

        # Reset enforcer's per-process gate cache for next call
        # (prevents stale cache across different tool calls)
        try:
            enforcer._gate_result_cache.clear()
        except (AttributeError, TypeError):
            pass

    return {
        "exit_code": exit_code,
        "stderr": captured_stderr.getvalue(),
        "stdout": captured_stdout.getvalue(),
    }


def _handle_client(conn):
    """Handle a single UDS client: read JSON request, run enforcer, respond."""
    try:
        conn.settimeout(5)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk

        if not buf:
            return

        request_str = buf.decode("utf-8").strip()

        # Validate JSON and handle ping
        try:
            parsed = json.loads(request_str)
        except json.JSONDecodeError:
            resp = {"exit_code": 2, "stderr": "[DAEMON] Invalid JSON\n", "stdout": ""}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return

        if parsed.get("method") == "ping":
            resp = {"exit_code": 0, "stderr": "", "stdout": "", "ping": "pong"}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return

        result = _run_enforcer(request_str)
        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except Exception as e:
        try:
            resp = {"exit_code": 2, "stderr": f"[DAEMON] Handler error: {e}\n", "stdout": ""}
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
        except Exception:
            pass
    finally:
        conn.close()


def _write_pid():
    """Write PID file atomically."""
    tmp = PID_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(os.getpid()))
    os.replace(tmp, PID_FILE)


def _cleanup():
    """Remove socket and PID file on exit."""
    global _server_socket
    if _server_socket is not None:
        try:
            _server_socket.close()
        except Exception:
            pass
        _server_socket = None
    for path in (SOCKET_PATH, PID_FILE):
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass


def _bind_socket():
    """Create, bind, and return a new server socket."""
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    srv.listen(4)
    srv.settimeout(1.0)
    return srv


def main():
    global _server_socket

    # Pre-import enforcer so first request is fast
    import enforcer  # noqa: F401

    # Create and bind server socket
    srv = _bind_socket()
    _server_socket = srv

    _write_pid()
    atexit.register(_cleanup)

    # Shutdown flag prevents rebind during intentional SIGTERM
    _shutting_down = False

    def _sigterm_handler(signum, frame):
        nonlocal _shutting_down
        _shutting_down = True
        _cleanup()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    print(f"[ENFORCER-DAEMON] Started (PID {os.getpid()}, socket {SOCKET_PATH})", file=sys.stderr)

    try:
        while True:
            try:
                conn, _ = srv.accept()
                t = threading.Thread(target=_handle_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                # Proactive watchdog: detect deleted socket file
                if not os.path.exists(SOCKET_PATH):
                    print("[ENFORCER-DAEMON] Socket file missing, rebinding", file=sys.stderr)
                    try:
                        srv.close()
                    except Exception:
                        pass
                    srv = _bind_socket()
                    _server_socket = srv
                continue
            except OSError:
                if _shutting_down:
                    break
                # Reactive rebind on accept() failure (EMFILE, etc.)
                print("[ENFORCER-DAEMON] Accept error, rebinding", file=sys.stderr)
                try:
                    srv.close()
                except Exception:
                    pass
                time.sleep(1)
                try:
                    srv = _bind_socket()
                    _server_socket = srv
                except OSError as e:
                    print(f"[ENFORCER-DAEMON] Rebind failed, retry in 5s: {e}", file=sys.stderr)
                    time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
        print("[ENFORCER-DAEMON] Stopped", file=sys.stderr)


if __name__ == "__main__":
    main()
