"""session_compressor.py — Dense session context compression for handoff.
Pure logic, no I/O. Token-efficient LLM ingestion format."""
import os

_CHARS_PER_TOKEN = 4  # ~4 chars/token


def compress_session_context(state: dict, max_tokens: int = 500) -> str:
    """Compress session state into a dense pipe-delimited string within token budget."""
    max_chars = max_tokens * _CHARS_PER_TOKEN
    parts = []

    # Files changed with verification tags
    files_edited = state.get("files_edited", [])
    verified = set(state.get("verified_fixes", []))
    pending = set(state.get("pending_verification", []))
    if files_edited:
        tagged = []
        for f in files_edited[-10:]:
            bn = os.path.basename(f)
            tagged.append(f"{bn}✓" if f in verified else (f"{bn}?" if f in pending else bn))
        parts.append("FILES:" + " ".join(tagged))

    # Verification ratio
    n_v, n_p = len(verified), len(pending)
    if n_v + n_p > 0:
        parts.append(f"VERIFY:{n_v}/{n_v + n_p}={n_v / (n_v + n_p):.0%}")

    # Test status
    if state.get("session_test_baseline"):
        code = state.get("last_test_exit_code")
        parts.append(f"TESTS:{'PASS' if code == 0 else f'FAIL(exit={code})'}")

    # Top error patterns
    error_counts = state.get("error_pattern_counts", {})
    if error_counts:
        top = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        parts.append("ERRORS:" + " ".join(f"{p}x{c}" for p, c in top))

    # Open causal chains
    chains = state.get("pending_chain_ids", [])
    if chains:
        parts.append(f"CHAINS:{len(chains)} open")

    # Bans + gate escalation
    bans = state.get("active_bans", [])
    if bans:
        parts.append("BANS:" + ",".join(bans[:3]))
    g6 = state.get("gate6_warn_count", 0)
    if g6 > 0:
        parts.append(f"GATE6:{g6}")

    # High-churn files (edit_streak >= 4)
    edit_streak = state.get("edit_streak", {})
    churn = sorted(
        [(f, c) for f, c in edit_streak.items() if isinstance(c, (int, float)) and c >= 4],
        key=lambda x: x[1], reverse=True,
    )[:3]
    if churn:
        parts.append("CHURN:" + " ".join(f"{os.path.basename(f)}({c}x)" for f, c in churn))

    result = " | ".join(parts)
    return result[:max_chars - 3] + "..." if len(result) > max_chars else result


def extract_key_decisions(state: dict) -> list:
    """Pull gate blocks, memory saves, and test results as short decision strings."""
    decisions = []
    tool_stats = state.get("tool_stats", {})

    # Gate blocks from tool_stats
    for tool_name, stats in tool_stats.items():
        if isinstance(stats, dict) and stats.get("blocked", 0) > 0:
            decisions.append(f"GATE_BLOCK:{tool_name} x{stats['blocked']}")

    # Legacy gate_blocks list (alternate state shape)
    for entry in state.get("gate_blocks", []):
        if isinstance(entry, dict):
            decisions.append(f"GATE_BLOCK:gate{entry.get('gate','?')}/{entry.get('tool','?')}")
        elif isinstance(entry, str):
            decisions.append(f"GATE_BLOCK:{entry}")

    # Memory saves
    mem_saves = sum(
        stats.get("count", 0)
        for name, stats in tool_stats.items()
        if isinstance(stats, dict) and "remember" in name
    )
    if mem_saves > 0:
        decisions.append(f"MEMORY:{mem_saves} saves")

    # Test outcome
    if state.get("session_test_baseline"):
        code = state.get("last_test_exit_code")
        if code is not None:
            decisions.append(f"TEST_{'PASS' if code == 0 else 'FAIL'}:exit={code}")

    # Resolved causal chains
    resolved = len(state.get("all_chain_ids", [])) - len(state.get("pending_chain_ids", []))
    if resolved > 0:
        decisions.append(f"FIXED:{resolved} chain(s) resolved")

    bans = state.get("active_bans", [])
    if bans:
        decisions.append(f"BANNED:{','.join(bans[:3])}")

    return decisions


def format_handoff(state: dict, decisions: list) -> str:
    """Produce a compact DONE / BLOCKED / NEXT handoff. Each item is max 1 line."""
    lines = []

    # DONE
    lines.append("DONE:")
    for f in state.get("verified_fixes", [])[-5:]:
        lines.append(f"  + {os.path.basename(f)} verified")
    for d in decisions:
        if d.startswith(("TEST_PASS", "FIXED", "MEMORY")):
            lines.append(f"  + {d}")
    if len(lines) == 1:
        lines.append("  (nothing verified this session)")

    # BLOCKED
    lines.append("BLOCKED:")
    pending = state.get("pending_verification", [])
    for f in pending[-3:]:
        lines.append(f"  ! {os.path.basename(f)} needs verification")
    chains = state.get("pending_chain_ids", [])
    if chains:
        lines.append(f"  ! {len(chains)} open causal chain(s)")
    for pat, cnt in sorted(state.get("error_pattern_counts", {}).items(), key=lambda x: x[1], reverse=True)[:2]:
        lines.append(f"  ! {pat} x{cnt}")
    for d in decisions:
        if d.startswith(("GATE_BLOCK", "TEST_FAIL", "BANNED")):
            lines.append(f"  ! {d}")
    if all(not l.startswith("  !") for l in lines):
        lines.append("  (none)")

    # NEXT
    lines.append("NEXT:")
    if pending:
        lines.append(f"  > verify {len(pending)} pending file(s)")
    if chains:
        lines.append(f"  > resolve {len(chains)} open causal chain(s)")
    edit_streak = state.get("edit_streak", {})
    for f, c in sorted(
        [(f, c) for f, c in edit_streak.items() if isinstance(c, (int, float)) and c >= 5],
        key=lambda x: x[1], reverse=True,
    )[:2]:
        lines.append(f"  > stabilize {os.path.basename(f)} ({c} edits)")
    if all(not l.startswith("  >") for l in lines):
        lines.append("  > continue current work")

    return "\n".join(lines)
