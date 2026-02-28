#!/usr/bin/env python3
"""Self-Healing Claude Framework — PreCompact Hook

Fires before context window compression. Saves a snapshot of the current
enforcer state to the capture queue so important context is not lost.

FAIL-OPEN: Entire script wrapped in try/except, always exits 0.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime

CAPTURE_QUEUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".capture_queue.jsonl")

TOOL_CATEGORIES = {
    "read_only": {"Read", "Grep", "Glob", "WebSearch", "WebFetch"},
    "write": {"Edit", "Write", "NotebookEdit"},
    "execution": {"Bash", "Task"},
}


def _categorize_tools(tool_stats):
    """Categorize tool usage into read_only, write, execution, memory, other."""
    categories = {"read_only": 0, "write": 0, "execution": 0, "memory": 0, "other": 0}
    for tool_name, info in tool_stats.items():
        count = info.get("count", 0) if isinstance(info, dict) else 0
        if tool_name in TOOL_CATEGORIES.get("read_only", set()):
            categories["read_only"] += count
        elif tool_name in TOOL_CATEGORIES.get("write", set()):
            categories["write"] += count
        elif tool_name in TOOL_CATEGORIES.get("execution", set()):
            categories["execution"] += count
        elif tool_name.startswith("mcp__memory__") or tool_name.startswith("mcp_memory_"):
            categories["memory"] += count
        else:
            categories["other"] += count
    return categories


def main():
    # Read session data from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        data = {}

    session_id = data.get("session_id", "main")

    # Load enforcer state for this session
    sys.path.insert(0, os.path.dirname(__file__))
    from shared.state import load_state
    state = load_state(session_id=session_id)

    # Extract snapshot metrics
    tool_call_count = state.get("tool_call_count", 0)
    files_read_count = len(state.get("files_read", []))
    pending_count = len(state.get("pending_verification", []))
    verified_count = len(state.get("verified_fixes", []))
    elapsed = time.time() - state.get("session_start", time.time())

    # Velocity metrics
    session_elapsed = max(elapsed, 1)  # Avoid division by zero
    tool_call_rate = round((tool_call_count / session_elapsed) * 60, 1)  # calls/min
    edit_count = pending_count + verified_count
    edit_rate = round((edit_count / session_elapsed) * 60, 1)  # edits/min
    velocity_tier = "high" if tool_call_rate > 40 else ("normal" if tool_call_rate > 10 else "low")

    # Extract enriched state data (error and chain tracking)
    error_pattern_counts = state.get("error_pattern_counts", {})
    pending_chain_ids = state.get("pending_chain_ids", [])
    active_bans = state.get("active_bans", [])
    gate6_warn_count = state.get("gate6_warn_count", 0)
    error_windows = state.get("error_windows", [])
    tool_stats = state.get("tool_stats", {})

    # Log snapshot to stderr (visible in Claude Code hook output)
    error_patterns_summary = f"{len(error_pattern_counts)} patterns" if error_pattern_counts else "none"
    chains_summary = f"{len(pending_chain_ids)} active" if pending_chain_ids else "none"
    bans_summary = f"{len(active_bans)} active" if active_bans else "none"

    print(
        f"[PreCompact] Snapshot before compaction: "
        f"{tool_call_count} tool calls, "
        f"{files_read_count} files read, "
        f"{pending_count} pending verification, "
        f"{verified_count} verified fixes, "
        f"{elapsed:.0f}s elapsed, "
        f"Velocity: {tool_call_rate} calls/min ({velocity_tier}) | "
        f"Errors: {error_patterns_summary}, "
        f"Chains: {chains_summary}, "
        f"Bans: {bans_summary}, "
        f"Gate6 warns: {gate6_warn_count}",
        file=sys.stderr,
    )

    # Build observation document for capture queue
    document_parts = [
        f"PreCompact snapshot: {tool_call_count} tool calls, "
        f"{files_read_count} files read, "
        f"{pending_count} pending, "
        f"{verified_count} verified, "
        f"{elapsed:.0f}s elapsed",
        f"Velocity: {tool_call_rate} calls/min, {edit_rate} edits/min ({velocity_tier})"
    ]

    # Add enriched state data
    if error_pattern_counts:
        top_errors = sorted(error_pattern_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        error_summary = "; ".join([f"{pattern}: {count}" for pattern, count in top_errors])
        document_parts.append(f"Error patterns: {error_summary}")

    if pending_chain_ids:
        document_parts.append(f"Active causal chains: {', '.join(pending_chain_ids)}")

    if active_bans:
        document_parts.append(f"Banned strategies: {', '.join(active_bans)}")

    if gate6_warn_count > 0:
        document_parts.append(f"Gate 6 warnings: {gate6_warn_count}")

    if error_windows:
        recent_errors = len([w for w in error_windows if time.time() - w.get("last_seen", 0) < 300])  # last 5 minutes
        if recent_errors > 0:
            document_parts.append(f"Recent errors (5m): {recent_errors}")

    if tool_stats:
        top_tools = sorted(tool_stats.items(), key=lambda x: x[1].get("count", 0), reverse=True)[:3]
        tools_summary = ", ".join(f"{tool}:{stats.get('count', 0)}" for tool, stats in top_tools)
        document_parts.append(f"Top tools: {tools_summary}")

    # Tool category breakdown
    tool_categories = _categorize_tools(tool_stats) if tool_stats else {}
    if tool_categories:
        cat = tool_categories
        document_parts.append(
            f"Tool mix: read={cat['read_only']}, write={cat['write']}, "
            f"exec={cat['execution']}, mem={cat['memory']}, other={cat['other']}"
        )

    # Tool mix sentiment analysis
    total_tools = sum(tool_categories.values()) or 1
    read_ratio = tool_categories.get("read_only", 0) / total_tools
    write_ratio = tool_categories.get("write", 0) / total_tools
    exec_ratio = tool_categories.get("execution", 0) / total_tools

    if write_ratio > 0.5:
        tool_mix_sentiment = "write_heavy"
    elif read_ratio > 0.7:
        tool_mix_sentiment = "read_dominant"
    elif exec_ratio < 0.1 and write_ratio > 0.2:
        tool_mix_sentiment = "unverified_edits"
    else:
        tool_mix_sentiment = "balanced"

    if tool_categories:
        document_parts.append(f"Session profile: {tool_mix_sentiment}")

    # High churn files (edit_streak >= 4)
    edit_streak = state.get("edit_streak", {})
    high_churn = {f: c for f, c in edit_streak.items() if isinstance(c, (int, float)) and c >= 4}
    if high_churn:
        churn_items = sorted(high_churn.items(), key=lambda x: x[1], reverse=True)
        churn_summary = ", ".join(f"{f} ({c}x)" for f, c in churn_items)
        document_parts.append(f"High churn: {churn_summary}")

    # Verified fix ratio
    verified_total = verified_count + pending_count
    verified_ratio = round(verified_count / max(verified_total, 1), 2)
    document_parts.append(f"Verified ratio: {verified_ratio:.2f}")

    # R:W ratio
    rw = files_read_count / max(len(state.get("files_edited", [])), 1)
    rw_rating = "good" if rw >= 4.0 else ("fair" if rw >= 2.0 else "poor")
    document_parts.append(f"R:W ratio: {rw:.1f} [{rw_rating}]")

    # Skill usage (only surface in long sessions to avoid noise)
    skill_usage = state.get("skill_usage", {})
    if session_elapsed > 1800 and skill_usage:  # 30+ min AND skills were used
        skills_summary = ", ".join(f"/{k} ({v}x)" for k, v in sorted(skill_usage.items(), key=lambda x: x[1], reverse=True)[:5])
        document_parts.append(f"Skills used: {skills_summary}")
    elif session_elapsed > 1800 and not skill_usage:
        document_parts.append("NOTE: Long session with no skill invocations")
    # Short sessions: say nothing about skills (no noise)

    # Session trajectory classification
    if verified_total > 0:
        success_rate = verified_count / verified_total
    else:
        success_rate = 1.0  # No edits = neutral
    if success_rate >= 0.9:
        trajectory = "high_confidence"
    elif success_rate >= 0.6:
        trajectory = "incremental"
    elif success_rate >= 0.3:
        trajectory = "iterative"
    else:
        trajectory = "struggling"
    document_parts.append(f"Trajectory: {trajectory}")

    document = ". ".join(document_parts)

    timestamp = datetime.now().isoformat()
    obs_id = hashlib.sha256(document.encode()).hexdigest()[:16]

    metadata = {
        "tool_name": "PreCompact",
        "session_id": session_id,
        "session_time": time.time(),
        "timestamp": timestamp,
        "has_error": "false",
        "error_pattern": "",
        "snapshot_type": "enriched",
        "tool_call_rate": tool_call_rate,
        "edit_rate": edit_rate,
        "velocity_tier": velocity_tier,
        "session_elapsed_seconds": round(session_elapsed, 0),
        "tool_stats_snapshot": {k: v.get("count", 0) for k, v in tool_stats.items()} if tool_stats else {},
        "tool_categories": tool_categories if tool_categories else {},
        "tool_mix_sentiment": tool_mix_sentiment if tool_categories else "unknown",
        "high_churn_count": len(high_churn),
        "verified_ratio": verified_ratio,
        "trajectory": trajectory,
        "rw_ratio": round(rw, 2),
        "rw_rating": rw_rating,
        "skill_count": len(skill_usage),
        "skills_used": list(skill_usage.keys())[:10],
    }

    observation = {
        "document": document,
        "metadata": metadata,
        "id": obs_id,
    }

    # Append to capture queue
    with open(CAPTURE_QUEUE, "a") as f:
        f.write(json.dumps(observation) + "\n")

    # Save to memory via UDS socket so post-compaction context is richer
    try:
        import socket as _socket
        sock_path = os.path.join(os.path.dirname(__file__), ".memory.sock")
        if os.path.exists(sock_path):
            sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(sock_path)
            msg = json.dumps({
                "method": "add_observation",
                "document": document,
                "metadata": {
                    "tool_name": "PreCompact",
                    "session_id": session_id,
                    "timestamp": timestamp,
                    "snapshot_type": "pre_compact",
                    "trajectory": trajectory,
                },
                "id": f"precompact_{obs_id}",
            })
            sock.sendall(msg.encode() + b"\n")
            sock.close()
    except Exception:
        pass  # Fail-open

    # Print active files to stderr so they survive compaction
    files_edited = state.get("files_edited", [])
    pending_verif = state.get("pending_verification", [])
    if files_edited or pending_verif:
        active_files = list(set(files_edited[-10:] + pending_verif[-5:]))
        print(f"[PreCompact] Active files: {', '.join(os.path.basename(f) for f in active_files)}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[PreCompact] Warning: {e}", file=sys.stderr)
    finally:
        sys.exit(0)
