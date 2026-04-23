"""Working memory writer for hybrid working memory system.

Reads operation tracker state and writes hooks/working-memory.md with three sections:

  Status     (~40 tokens)  — current op, last op. Updated every turn.
  Operations (+60-80/op)   — completed op summaries, FIFO eviction at ~650 tokens.
  Context    (+300-510)    — causal chains, errors, hot files. Written at threshold.

Total file cap: ~1200 tokens (estimated as len(text) / 4).
Atomic writes: tmp + os.replace() — safe against concurrent UserPromptSubmit/PostToolUse.
"""

import logging
import hashlib
import os
import subprocess

logger = logging.getLogger(__name__)

# ── Token budget constants ────────────────────────────────────────────────────

TOKEN_CAP = 1200  # Content token budget (headers/structural overhead excluded)
OPS_SECTION_TOKEN_CAP = 650  # Content token budget for op lines only (header excluded)
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


def inject_enforcer_fields(tracker_state: dict, enforcer_state: dict) -> None:
    """Inject enforcer state fields into tracker_state for context section.

    The context section needs data from both operation tracker and enforcer state.
    Prefixed with _ to avoid collisions with tracker's own fields.
    """
    tracker_state["_error_pattern_counts"] = enforcer_state.get(
        "error_pattern_counts", {}
    )
    tracker_state["_edit_streak"] = enforcer_state.get("edit_streak", {})
    tracker_state["_files_read"] = enforcer_state.get("files_read", [])


def inject_dag_fields(tracker_state: dict, dag) -> None:
    """Inject DAG context into tracker_state for header and context section.

    Prefixed with _dag_ to avoid collisions with tracker's own fields.
    Fail-open: exceptions are silently caught.
    """
    try:
        binfo = dag.current_branch_info()
        tracker_state["_dag_branch"] = binfo.get("name", "")
        tracker_state["_dag_branch_label"] = dag.get_branch_label()
        tracker_state["_dag_node_count"] = binfo.get("msg_count", 0)
        tracker_state["_dag_total_branches"] = binfo.get("total_branches", 0)
    except Exception:
        pass  # Fail-open
    tracker_state["_deferred_items"] = enforcer_state.get("deferred_items", [])


# ── Section builders ──────────────────────────────────────────────────────────


_BOOKKEEPING_FILES = {
    "working-summary.md",
    "working-memory.md",
    "LIVE_STATE.json",
    ".statusline_snapshot.json",
}


def _is_bookkeeping_op(op: dict) -> bool:
    """Return True if all files in an op are bookkeeping files."""
    files = op.get("files", [])
    return bool(files) and all(os.path.basename(f) in _BOOKKEEPING_FILES for f in files)


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

    # Last completed op — skip bookkeeping files
    last = None
    if completed:
        for op in reversed(completed):
            if not _is_bookkeeping_op(op):
                last = op
                break
    if last:
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

    # Causal chain — link ops where earlier op wrote a file that later op touches
    _WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
    completed = tracker_state.get("completed_ops", [])
    if len(completed) >= 2:
        chains = []
        current_chain = [completed[0]]
        for prev_op, next_op in zip(completed, completed[1:]):
            prev_files = set(prev_op.get("files", []))
            next_files = set(next_op.get("files", []))
            prev_tools = set(prev_op.get("tools", []))
            # Require file overlap AND earlier op has a write tool
            if prev_files & next_files and prev_tools & _WRITE_TOOLS:
                current_chain.append(next_op)
            else:
                if len(current_chain) >= 2:
                    chains.append(current_chain)
                current_chain = [next_op]
        if len(current_chain) >= 2:
            chains.append(current_chain)

        if chains:
            lines.append("### Causal Chain")
            for chain in chains[-2:]:  # Show at most 2 chains
                first_id = chain[0]["id"]
                last_id = chain[-1]["id"]
                # Collect unique files across chain, preserve order
                seen = set()
                chain_files = []
                for op in chain:
                    for f in op.get("files", []):
                        name = os.path.basename(f)
                        if name not in seen:
                            seen.add(name)
                            chain_files.append(name)
                files_str = " → ".join(chain_files)
                lines.append(f"- Op{first_id}→Op{last_id} ({files_str})")
        else:
            lines.append("### Causal Chain")
            lines.append("- (no linked operations detected)")
    else:
        lines.append("### Causal Chain")
        lines.append("- (too few operations)")

    # Errors — from error_pattern_counts (enforcer state) + unresolved ops
    error_counts = tracker_state.get("_error_pattern_counts", {})
    unresolved = tracker_state.get("unresolved_errors", [])
    lines.append("### Errors")
    if error_counts or unresolved:
        for pattern, count in sorted(
            error_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            lines.append(f"- {pattern}: {count}x")
        for e in unresolved[-3:]:
            lines.append(f"- {e[:100]}")
    else:
        lines.append("- (none)")

    # Deferred items — strategies that failed and were deferred for later
    deferred = tracker_state.get("_deferred_items", [])
    if deferred:
        lines.append("### Deferred")
        for item in deferred[-3:]:
            strategy = item.get("strategy", "?")[:40]
            err_sig = item.get("error_signature", "?")[:30]
            fails = item.get("fail_count", 0)
            lines.append(f"- {strategy} ({err_sig}, {fails}x failed)")

    # DAG Branch — active task context
    dag_branch_ctx = tracker_state.get("_dag_branch", "")
    dag_label_ctx = tracker_state.get("_dag_branch_label", "")
    dag_nodes_ctx = tracker_state.get("_dag_node_count", 0)
    dag_total_ctx = tracker_state.get("_dag_total_branches", 0)
    if dag_branch_ctx or dag_nodes_ctx:
        lines.append("### DAG Context")
        dag_line = f"- Branch: {dag_branch_ctx or 'main'}"
        if dag_label_ctx:
            dag_line += f" (task={dag_label_ctx})"
        if dag_nodes_ctx:
            dag_line += f", {dag_nodes_ctx} nodes"
        if dag_total_ctx > 1:
            dag_line += f", {dag_total_ctx} branches"
        lines.append(dag_line)

    # Hot Files — merge edit counts + read counts per file
    edit_streak = tracker_state.get("_edit_streak", {})
    files_read_list = tracker_state.get("_files_read", [])
    # Count reads per file
    read_counts = {}
    for f in files_read_list:
        read_counts[f] = read_counts.get(f, 0) + 1
    # Merge all files that were either edited or read
    all_files = set(edit_streak.keys()) | set(read_counts.keys())
    if all_files:
        hot = []
        for f in all_files:
            edits = edit_streak.get(f, 0)
            reads = read_counts.get(f, 0)
            hot.append((f, edits, reads))
        # Sort by total activity (edits + reads), show top 8
        hot.sort(key=lambda x: x[1] + x[2], reverse=True)
        lines.append("### Hot Files")
        for f, edits, reads in hot[:8]:
            lines.append(f"- {f}: {edits}e {reads}r")
    else:
        lines.append("### Hot Files")
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

    dag_branch = tracker_state.get("_dag_branch", "")
    dag_label = tracker_state.get("_dag_branch_label", "")
    dag_nodes = tracker_state.get("_dag_node_count", 0)

    dag_suffix = ""
    if dag_branch and dag_branch not in ("main", ""):
        dag_suffix = f" | DAG: {dag_branch}"
        if dag_label:
            dag_suffix += f":{dag_label}"
    elif dag_nodes > 0:
        dag_suffix = f" | DAG: {dag_nodes}n"

    header = (
        f"# Working Memory (auto-generated — do not edit)\n"
        f"## Session {session_id[:16] if len(session_id) > 16 else session_id}"
        f" | Branch: {branch}{dag_suffix}\n\n"
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
    """Writes hooks/working-memory.md with three layered sections.

    Writes to hooks/ (not rules/) so the file is injected on-demand by
    boot.py/post_compact.py instead of auto-loaded on every API call.

    Three sections, each updated on a different trigger:
      - write_status()    — every UserPromptSubmit (base layer)
      - write_operations()— on operation boundary (accumulate layer)
      - write_expanded()  — at context threshold (expand layer)
    """

    def __init__(self, hooks_dir: str, project_dir: str = ""):
        self._hooks_dir = hooks_dir
        if project_dir:
            # Project session: write to {project_dir}/.claude/hooks/
            proj_hooks = os.path.join(project_dir, ".claude", "hooks")
            os.makedirs(proj_hooks, exist_ok=True)
            self._output_path = os.path.join(proj_hooks, "working-memory.md")
        else:
            self._output_path = os.path.join(hooks_dir, "working-memory.md")
        self._expand_written = False
        self._last_hash = ""  # Skip writes when content unchanged

    # ── Public API ────────────────────────────────────────────────────────────

    def _write_if_changed(self, content: str) -> bool:
        """Write file only if content changed. Returns True if written."""
        h = hashlib.md5(content.encode()).hexdigest()
        if h == self._last_hash:
            return False
        _atomic_write(self._output_path, content)
        self._last_hash = h
        return True

    def write_status(self, tracker_state: dict) -> None:
        """Update the Status section. Called every UserPromptSubmit turn.

        Skips the write if content hasn't changed since last call.
        """
        try:
            include_ctx = self._expand_written or tracker_state.get(
                "expand_written", False
            )
            content = _build_full_file(tracker_state, include_context=include_ctx)
            self._write_if_changed(content)
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
            self._write_if_changed(content)
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
