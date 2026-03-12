#!/usr/bin/env bash
# Launch memory server in SSE mode (shared across all Claude sessions).
# Usage: ./memory_sse.sh [start|stop|status|restart]
#
# The server listens on 127.0.0.1:8741 by default.
# Override with MEMORY_SSE_PORT=XXXX environment variable.

set -euo pipefail

PORT="${MEMORY_SSE_PORT:-8741}"
PIDFILE="/tmp/memory_server_sse.pid"
LOGFILE="/tmp/memory_server_sse.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER="$SCRIPT_DIR/memory_server.py"

_is_running() {
    if [ -f "$PIDFILE" ]; then
        local pid
        pid=$(cat "$PIDFILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$PIDFILE"
    fi
    return 1
}

cmd_start() {
    if _is_running; then
        echo "Memory SSE server already running (PID $(cat "$PIDFILE"), port $PORT)"
        return 0
    fi
    echo "Starting memory SSE server on port $PORT..."
    nohup /usr/bin/python3 "$SERVER" --sse --port "$PORT" >> "$LOGFILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PIDFILE"
    # Wait for server to be ready (up to 30s for model load)
    for i in $(seq 1 30); do
        if curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT/sse" 2>/dev/null; then
            echo "Memory SSE server ready (PID $pid, port $PORT)"
            return 0
        fi
        sleep 1
    done
    echo "Warning: server started but not responding after 30s (PID $pid)"
    echo "Check logs: $LOGFILE"
}

cmd_stop() {
    if ! _is_running; then
        echo "Memory SSE server not running"
        return 0
    fi
    local pid
    pid=$(cat "$PIDFILE")
    echo "Stopping memory SSE server (PID $pid)..."
    kill "$pid" 2>/dev/null
    # Wait for clean shutdown
    for i in $(seq 1 5); do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PIDFILE"
            echo "Stopped"
            return 0
        fi
        sleep 1
    done
    kill -9 "$pid" 2>/dev/null
    rm -f "$PIDFILE"
    echo "Force killed"
}

cmd_status() {
    if _is_running; then
        local pid
        pid=$(cat "$PIDFILE")
        local rss
        rss=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ')
        echo "Memory SSE server: RUNNING (PID $pid, port $PORT, RSS ${rss:-?}KB)"
    else
        echo "Memory SSE server: STOPPED"
    fi
}

cmd_restart() {
    cmd_stop
    cmd_start
}

case "${1:-start}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    *)       echo "Usage: $0 {start|stop|status|restart}" ;;
esac
