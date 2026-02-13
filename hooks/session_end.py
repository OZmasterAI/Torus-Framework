#!/usr/bin/env python3
"""Self-Healing Claude Framework — Session End Hook

Fires on SessionEnd to:
1. Flush the capture queue to ChromaDB (observations collection)
2. Increment session_count in LIVE_STATE.json

Fail-open: always exits 0.
"""
import glob
import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
CAPTURE_QUEUE = os.path.join(HOOKS_DIR, ".capture_queue.jsonl")


def session_summary():
    """Load most recent session state and print compact metrics."""
    try:
        # Find most recent state_*.json file
        state_files = glob.glob(os.path.join(HOOKS_DIR, "state_*.json"))
        if not state_files:
            return {}

        # Sort by modification time, get most recent
        latest_state_file = max(state_files, key=os.path.getmtime)

        with open(latest_state_file, "r") as f:
            state = json.load(f)

        # Extract metrics
        reads = len(state.get("files_read", []))
        edits = len(state.get("edit_streak", {}))
        errors = len(state.get("error_pattern_counts", {}))
        verified = len(state.get("verified_fixes", []))
        pending = len(state.get("pending_verification", []))

        # Print compact summary to stderr
        print(
            f"[SESSION_END] Metrics: {reads}R {edits}W | {errors} errors | {verified}V {pending}P",
            file=sys.stderr
        )

        return {
            "reads": reads,
            "edits": edits,
            "errors": errors,
            "verified": verified,
            "pending": pending
        }
    except Exception as e:
        print(f"[SESSION_END] Summary error (non-fatal): {e}", file=sys.stderr)
        return {}


def flush_capture_queue():
    """Flush .capture_queue.jsonl into ChromaDB observations collection."""
    if not os.path.exists(CAPTURE_QUEUE) or os.path.getsize(CAPTURE_QUEUE) == 0:
        print("[SESSION_END] Flushed 0 observations", file=sys.stderr)
        return
    with open(CAPTURE_QUEUE, "r") as f:
        lines = f.readlines()

    import chromadb
    client = chromadb.PersistentClient(path=MEMORY_DIR)
    obs_col = client.get_or_create_collection(
        name="observations", metadata={"hnsw:space": "cosine"}
    )
    docs, metas, ids, seen = [], [], [], set()
    for line in lines:
        try:
            obs = json.loads(line.strip())
            if "document" in obs and "id" in obs and obs["id"] not in seen:
                docs.append(obs["document"])
                metas.append(obs.get("metadata", {}))
                ids.append(obs["id"])
                seen.add(obs["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    if docs:
        for i in range(0, len(docs), 100):
            obs_col.upsert(
                documents=docs[i:i + 100],
                metadatas=metas[i:i + 100],
                ids=ids[i:i + 100],
            )
    # Truncate queue after successful flush
    with open(CAPTURE_QUEUE, "w") as f:
        pass
    print(f"[SESSION_END] Flushed {len(docs)} observations", file=sys.stderr)


def increment_session_count(metrics=None):
    """Atomically increment session_count in LIVE_STATE.json."""
    state = {}
    if os.path.exists(LIVE_STATE_FILE):
        try:
            with open(LIVE_STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}
    state["session_count"] = state.get("session_count", 0) + 1

    # Store session metrics if provided
    if metrics:
        state["last_session_metrics"] = metrics

    tmp = LIVE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE_STATE_FILE)
    print(f"[SESSION_END] Session {state['session_count']} complete", file=sys.stderr)


def main():
    try:
        # Read stdin (session data, may include session_id)
        try:
            _session_data = json.loads(sys.stdin.read())
        except (json.JSONDecodeError, ValueError):
            _session_data = {}

        # Get session summary metrics
        metrics = {}
        try:
            metrics = session_summary()
        except Exception as e:
            print(f"[SESSION_END] Summary error (non-fatal): {e}", file=sys.stderr)

        flush_capture_queue()
        increment_session_count(metrics)
    except Exception as e:
        print(f"[SESSION_END] Error (non-fatal): {e}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
