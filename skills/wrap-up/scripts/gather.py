#!/usr/bin/env python3
"""Gather all prerequisite data for wrap-up and output JSON to stdout.

Claude uses this JSON to write the intelligent parts (LIVE_STATE.json).
Every data source is wrapped in try/except so failures are non-fatal (fail-open).
"""

import json
import os
import subprocess
import sys
import time

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
LIVE_STATE_FILE = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")

# Make shared modules importable
sys.path.insert(0, HOOKS_DIR)

from shared.chromadb_socket import (
    WorkerUnavailable,
    backup as socket_backup,
    count as socket_count,
    is_worker_available,
    query as socket_query,
)


def gather_live_state(warnings):
    """Load LIVE_STATE.json content."""
    try:
        with open(LIVE_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        warnings.append(f"live_state: {e}")
        return {}


def gather_handoff(warnings):
    """Load last session summary and staleness info from LIVE_STATE.json."""
    result = {"content": "", "age_hours": 999.0, "stale": True}
    try:
        age_hours = (time.time() - os.path.getmtime(LIVE_STATE_FILE)) / 3600
        result["age_hours"] = round(age_hours, 2)
        result["stale"] = age_hours > 4
        with open(LIVE_STATE_FILE, "r") as f:
            live = json.load(f)
        result["content"] = live.get("what_was_done", "")
    except Exception as e:
        warnings.append(f"handoff: {e}")
    return result


def gather_git(warnings):
    """Gather git status for CLAUDE_DIR."""
    result = {"clean": True, "changes": [], "diff_stat": ""}
    try:
        porcelain = subprocess.run(
            ["git", "-C", CLAUDE_DIR, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l.strip() for l in porcelain.stdout.strip().splitlines() if l.strip()]
        result["clean"] = len(lines) == 0
        result["changes"] = lines
    except Exception as e:
        warnings.append(f"git status: {e}")
    try:
        diff_stat = subprocess.run(
            ["git", "-C", CLAUDE_DIR, "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        result["diff_stat"] = diff_stat.stdout.strip()
    except Exception as e:
        warnings.append(f"git diff: {e}")
    return result


def _is_mcp_process_running():
    """Check if memory_server.py is running as a process."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "memory_server.py"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def gather_memory(warnings):
    """Check memory accessibility and count.

    Uses UDS socket first (most accurate). Falls back to process detection
    when the socket isn't reachable — the MCP server may be running but
    the socket is only visible inside the MCP process context.
    """
    result = {"count": 0, "accessible": False, "count_reliable": True}
    try:
        result["accessible"] = is_worker_available(retries=2, delay=0.1)
    except Exception as e:
        warnings.append(f"memory accessible: {e}")
    if not result["accessible"]:
        # Socket unreachable — check if MCP process is alive (common when
        # gather.py runs as a subprocess outside the MCP context)
        if _is_mcp_process_running():
            result["accessible"] = True
            # Expected when gather.py runs as subprocess — socket is process-local
            # but MCP is confirmed alive via pgrep. Not worth warning about.
    if result["accessible"]:
        try:
            result["count"] = socket_count("knowledge")
        except (WorkerUnavailable, Exception) as e:
            # If socket failed but process is running, estimate count from stats-cache
            stats_cache = os.path.join(CLAUDE_DIR, "stats-cache.json")
            try:
                with open(stats_cache) as f:
                    cached = json.load(f)
                age = time.time() - cached.get("ts", 0)
                if age < 120:
                    result["count"] = cached.get("mem_count", 0)
                    result["count_reliable"] = False
                    warnings.append("memory count: used stats-cache fallback")
                else:
                    result["count_reliable"] = False
                    warnings.append(f"memory count: stats-cache expired ({int(age)}s old)")
            except Exception:
                result["count_reliable"] = False
                warnings.append(f"memory count: {e}")
    return result


def gather_backup(warnings):
    """Trigger ChromaDB backup and return status."""
    try:
        if not is_worker_available(retries=2, delay=0.1):
            warnings.append("backup: worker unavailable")
            return {}
        result = socket_backup()
        size_mb = round(result.get("size_bytes", 0) / (1024 * 1024), 2)
        return {"status": "ok", "size_mb": size_mb}
    except Exception as e:
        warnings.append(f"backup: {e}")
        return {}


def gather_promotion_candidates(warnings):
    """Find recurring error patterns that appear 3+ times."""
    candidates = []
    try:
        resp = socket_query(
            "knowledge",
            ["recurring error pattern"],
            n_results=10,
            include=["metadatas"],
        )
        # resp structure: {"ids": [[...]], "metadatas": [[...]], ...}
        metadatas = resp.get("metadatas", [[]])[0] if resp else []
        pattern_counts = {}
        for meta in metadatas:
            if not meta:
                continue
            tags = meta.get("tags", "")
            if "type:error" in str(tags):
                pattern = meta.get("error_pattern", meta.get("tags", "unknown"))
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        for pattern, cnt in pattern_counts.items():
            if cnt >= 3:
                candidates.append({"pattern": str(pattern), "count": cnt})
    except (WorkerUnavailable, Exception) as e:
        warnings.append(f"promotion_candidates: {e}")
    return candidates


def gather_recent_learnings(warnings):
    """Fetch recent learning-type memories."""
    learnings = []
    try:
        resp = socket_query(
            "knowledge",
            ["type:learning recent session"],
            n_results=5,
            include=["documents", "metadatas"],
        )
        ids = resp.get("ids", [[]])[0] if resp else []
        docs = resp.get("documents", [[]])[0] if resp else []
        for i, doc in enumerate(docs):
            mid = ids[i] if i < len(ids) else f"unknown_{i}"
            preview = (doc[:100] + "...") if len(doc) > 100 else doc
            learnings.append({"preview": preview, "id": mid})
    except (WorkerUnavailable, Exception) as e:
        warnings.append(f"recent_learnings: {e}")
    return learnings


def compute_risk_level(handoff, git, memory):
    """Determine overall risk level."""
    if not memory["accessible"]:
        return "RED"
    if memory["count"] == 0 and memory.get("count_reliable", True):
        return "RED"
    if memory["count"] == 0 and not memory.get("count_reliable", True):
        return "YELLOW"
    if handoff["stale"] or not git["clean"]:
        return "YELLOW"
    return "GREEN"


def main():
    warnings = []

    live_state = gather_live_state(warnings)
    handoff = gather_handoff(warnings)
    git = gather_git(warnings)
    memory = gather_memory(warnings)
    backup = gather_backup(warnings)
    promotion_candidates = gather_promotion_candidates(warnings)
    recent_learnings = gather_recent_learnings(warnings)
    risk_level = compute_risk_level(handoff, git, memory)

    # Memory pruning nudge — threshold check, no MCP call
    memory_pruning_nudge = ""
    mem_count = memory.get("count", 0)
    if mem_count >= 700:
        memory_pruning_nudge = f"Memory DB at {mem_count} entries. Run maintenance(action='stale') to find cleanup candidates."

    result = {
        "live_state": live_state,
        "handoff": handoff,
        "git": git,
        "memory": memory,
        "backup": backup,
        "promotion_candidates": promotion_candidates,
        "recent_learnings": recent_learnings,
        "risk_level": risk_level,
        "warnings": warnings,
        "memory_pruning_nudge": memory_pruning_nudge,
    }

    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e), "warnings": ["script crash"]}, sys.stdout, indent=2)
