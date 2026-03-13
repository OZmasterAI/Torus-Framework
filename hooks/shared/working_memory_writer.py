"""Working memory writer for hybrid working memory system.

Reads operation tracker state and writes rules/working-memory.md with three sections:

  Status     (~40 tokens)  — current op, last op. Updated every turn.
  Operations (+60-80/op)   — completed op summaries, FIFO eviction at ~500 tokens.
  Context    (+200-350)    — key decisions, unresolved errors. Written at threshold.

Total file cap: ~800 tokens (estimated as len(text) / 4).
Atomic writes: tmp + os.replace() — safe against concurrent UserPromptSubmit/PostToolUse.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# ── Token budget constants ────────────────────────────────────────────────────

TOKEN_CAP = 800  # Content token budget (headers/structural overhead excluded)
OPS_SECTION_TOKEN_CAP = 500  # Content token budget for op lines only (header excluded)
CHARS_PER_TOKEN = 4  # Rough estimate: 1 token ≈ 4 chars


def _token_estimate(text: str) -> int:
    """Rough token estimate: len(text) / CHARS_PER_TOKEN."""
    return max(0, len(text) // CHARS_PER_TOKEN)


# ── Git branch helper ─────────────────────────────────────────────────────────


def _get_branch() -> str:
    """Get current git branch name, fail-open returns 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=os.path.expanduser("~/.claude"),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ── Section builders ──────────────────────────────────────────────────────────


def _build_status_section(tracker_state: dict) -> str:
    """Build the Status section (~40 tokens)."""
    session_id = tracker_state.get("_session_id", "")
    op_id = tracker_state.get("current_op_id", 1)
    op_type = tracker_state.get("current_op_type")
    op_purpose = tracker_state.get("current_op_purpose", "")
    op_files = tracker_state.get("current_op_files", [])

    completed = tracker_state.get("completed_ops", [])

    # Active line
    if op_type is not None:
        files_str = ", ".join(os.path.basename(f) for f in op_files[:3]) or "(none)"
        active_line = (
            f"Active: [Op{op_id}: {op_type}] {op_purpose[:50]} | Files: {files_str}"
        )
    else:
        active_line = "Active: (none)"

    # Last completed op
    if completed:
        last = completed[-1]
        last_id = last.get("id", "?")
        last_type = last.get("type", "?")
        last_purpose = last.get("purpose", "")[:50]
        last_outcome = last.get("outcome", "?")
        last_line = f"Last: [Op{last_id}: {last_type}] {last_purpose} [{last_outcome}]"
    else:
        last_line = "Last: (none)"

    return f"## Status\n{active_line}\n{last_line}\n"


def _build_operations_section(tracker_state: dict) -> str:
    """Build the Operations section, FIFO evict oldest when over OPS_SECTION_TOKEN_CAP.

    Token budget counts only op content lines — the '## Operations' header is free overhead.
    """
    completed = tracker_state.get("completed_ops", [])
    if not completed:
        return "## Operations\n(none yet)\n"

    # Format all ops, then FIFO evict oldest until content fits under token cap
    lines = [_format_op_line(op) for op in completed]
    while lines and _token_estimate("\n".join(lines)) > OPS_SECTION_TOKEN_CAP:
        lines.pop(0)  # Evict oldest

    return "## Operations\n" + "\n".join(lines) + "\n"


def _format_op_line(op: dict) -> str:
    """Format a single completed operation as a summary line."""
    op_id = op.get("id", "?")
    op_type = op.get("type", "?")
    purpose = op.get("purpose", "")[:60]
    outcome = op.get("outcome", "?")

    # Include key files (up to 2)
    files = op.get("files", [])
    files_part = ""
    if files:
        names = [os.path.basename(f) for f in files[:2]]
        files_part = f" ({', '.join(names)})"

    return f"- [Op{op_id}: {op_type}] {purpose}{files_part} [{outcome}]"


def _build_context_section(tracker_state: dict) -> str:
    """Build the Context section (+200-350 tokens). Written at threshold."""
    lines = ["## Context (expanded at threshold)"]

    # Key decisions
    decisions = tracker_state.get("decisions", [])
    lines.append("### Key Decisions")
    if decisions:
        for d in decisions[-5:]:
            lines.append(f"- {d[:120]}")
    else:
        lines.append("- (none captured)")

    # Unresolved errors
    unresolved = tracker_state.get("unresolved_errors", [])
    lines.append("### Unresolved")
    if unresolved:
        for e in unresolved[-3:]:
            lines.append(f"- {e[:100]}")
    else:
        lines.append("- (none)")

    # Files modified
    completed = tracker_state.get("completed_ops", [])
    modified = []
    for op in completed:
        if op.get("type") in ("write", "verify"):
            for f in op.get("files", []):
                if f not in modified:
                    modified.append(f)

    lines.append("### Files Modified This Session")
    if modified:
        for f in modified[-8:]:
            lines.append(f"- {f}")
    else:
        lines.append("- (none)")

    return "\n".join(lines) + "\n"


def _content_token_estimate(tracker_state: dict, include_context: bool = False) -> int:
    """Estimate tokens for content only (excludes structural headers).

    Content = status lines + op lines + context body.
    Headers like '## Status', '## Operations', '# Working Memory...' are free overhead.
    """
    tokens = 0

    # Status content: Active + Last lines
    status = _build_status_section(tracker_state)
    # Strip the "## Status\n" header, count only the Active/Last lines
    status_lines = [l for l in status.split("\n") if l and not l.startswith("## ")]
    tokens += _token_estimate("\n".join(status_lines))

    # Operations content: op summary lines only (with same FIFO eviction as build)
    completed = tracker_state.get("completed_ops", [])
    if completed:
        lines = [_format_op_line(op) for op in completed]
        # Apply same FIFO eviction as _build_operations_section
        while lines and _token_estimate("\n".join(lines)) > OPS_SECTION_TOKEN_CAP:
            lines.pop(0)
        tokens += _token_estimate("\n".join(lines))

    # Context content: decision/error/file lines only
    if include_context:
        context = _build_context_section(tracker_state)
        context_lines = [
            l
            for l in context.split("\n")
            if l and not l.startswith("## ") and not l.startswith("### ")
        ]
        tokens += _token_estimate("\n".join(context_lines))

    return tokens


def _build_full_file(
    tracker_state: dict,
    include_context: bool = False,
) -> str:
    """Build the complete working-memory.md content."""
    session_id = tracker_state.get("_session_id", "session")
    branch = tracker_state.get("_branch", _get_branch())

    header = (
        f"# Working Memory (auto-generated — do not edit)\n"
        f"## Session {session_id[:16] if len(session_id) > 16 else session_id}"
        f" | Branch: {branch}\n\n"
    )

    status = _build_status_section(tracker_state)
    ops = _build_operations_section(tracker_state)

    content = header + status + "\n" + ops

    if include_context:
        context = _build_context_section(tracker_state)
        content += "\n" + context

    return content


# ── Atomic file write ─────────────────────────────────────────────────────────


def _atomic_write(path: str, content: str) -> None:
    """Write content atomically using tmp + os.replace()."""
    tmp = path + f".tmp.{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"working_memory_writer: atomic write failed for {path}: {e}")
        # Clean up tmp if it exists
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


# ── WorkingMemoryWriter ───────────────────────────────────────────────────────


class WorkingMemoryWriter:
    """Writes rules/working-memory.md with three layered sections.

    Three sections, each updated on a different trigger:
      - write_status()    — every UserPromptSubmit (base layer)
      - write_operations()— on operation boundary (accumulate layer)
      - write_expanded()  — at context threshold (expand layer)
    """

    def __init__(self, rules_dir: str):
        self._rules_dir = rules_dir
        self._output_path = os.path.join(rules_dir, "working-memory.md")
        self._expand_written = False

    # ── Public API ────────────────────────────────────────────────────────────

    def write_status(self, tracker_state: dict) -> None:
        """Update the Status section. Called every UserPromptSubmit turn.

        Rewrites the entire file with current Status + last Operations + optional Context.
        Status-only rewrite is safe because the file is always regenerated from tracker state.
        """
        try:
            include_ctx = self._expand_written or tracker_state.get(
                "expand_written", False
            )
            content = _build_full_file(tracker_state, include_context=include_ctx)
            _atomic_write(self._output_path, content)
        except Exception as e:
            logger.warning(f"working_memory_writer.write_status failed: {e}")

    def write_operations(self, tracker_state: dict) -> None:
        """Update the Operations section on operation boundary.

        Rewrites the file with updated completed ops list.
        """
        try:
            include_ctx = self._expand_written or tracker_state.get(
                "expand_written", False
            )
            content = _build_full_file(tracker_state, include_context=include_ctx)
            _atomic_write(self._output_path, content)
        except Exception as e:
            logger.warning(f"working_memory_writer.write_operations failed: {e}")

    def write_expanded(self, tracker_state: dict) -> None:
        """Write the full file including the Context (expand) section.

        Called once at context threshold. Sets expand_written flag both on the
        instance and in the tracker_state dict (caller must persist tracker_state).
        """
        try:
            content = _build_full_file(tracker_state, include_context=True)
            # Enforce token cap on content only (headers are free overhead)
            if _content_token_estimate(tracker_state, include_context=True) > TOKEN_CAP:
                content = self._trim_to_cap(tracker_state)
            _atomic_write(self._output_path, content)
            self._expand_written = True
            tracker_state["expand_written"] = True
        except Exception as e:
            logger.warning(f"working_memory_writer.write_expanded failed: {e}")

    def clear_expand(self) -> None:
        """Reset expand_written flag (call after /clear)."""
        self._expand_written = False

    def get_token_estimate(self) -> int:
        """Return estimated token count of the current working-memory.md file."""
        try:
            if not os.path.exists(self._output_path):
                return 0
            with open(self._output_path) as f:
                content = f.read()
            return _token_estimate(content)
        except Exception:
            return 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _trim_to_cap(self, tracker_state: dict) -> str:
        """Build content that fits within TOKEN_CAP by reducing ops count.

        Token cap applies to content only — headers are free overhead.
        """
        # Try with full context first, then reduce ops
        state = dict(tracker_state)
        completed = list(state.get("completed_ops", []))

        while completed:
            state["completed_ops"] = completed
            if _content_token_estimate(state, include_context=True) <= TOKEN_CAP:
                return _build_full_file(state, include_context=True)
            # Evict oldest op
            completed = completed[1:]

        # Fallback: no ops, just status + context
        state["completed_ops"] = []
        return _build_full_file(state, include_context=True)
