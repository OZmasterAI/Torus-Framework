"""Zero-overhead context compression — TurboQuant "every bit carries signal" for tokens.

Precomputed format templates (like TurboQuant codebooks) compress memory search
results, boot injection, and post-compact re-injection with zero runtime cost.

Public API:
    compact_result(r)         -> str   # ~35 tokens per result
    minimal_result(r)         -> str   # ~20 tokens per result
    compress_results(results) -> list[str]  # adaptive budget
    compress_boot_state(d)    -> str   # single-line state
    compress_postcompact(wm, ws, dag) -> str  # trimmed re-injection
    estimate_tokens(text)     -> int   # rough token count
"""


def estimate_tokens(text):
    """Rough token estimate: chars // 4 + 1."""
    if not text:
        return 0
    return len(text) // 4 + 1


def _top_tags(tags_str, n=3):
    """Extract top N bare tags, stripping type:/area:/priority: prefixes."""
    if not tags_str:
        return ""
    raw = [t.strip() for t in tags_str.split(",") if t.strip()]
    bare = []
    for tag in raw:
        # Strip known prefixes
        for prefix in ("type:", "area:", "priority:", "outcome:", "error_pattern:"):
            if tag.startswith(prefix):
                tag = tag[len(prefix) :]
                break
        if tag and tag not in bare:
            bare.append(tag)
    return ",".join(bare[:n])


def compact_result(r):
    """Compact format: [id|rel|Ttier] preview {tags} — ~35 tokens."""
    rid = r.get("id", "?")[:8]
    rel = r.get("relevance", 0)
    tier = r.get("tier", 2)
    preview = (r.get("preview") or "")[:80]
    tags = _top_tags(r.get("tags", ""))
    tag_part = f" {{{tags}}}" if tags else ""
    return f"[{rid}|{rel:.2f}|T{tier}] {preview}{tag_part}"


def minimal_result(r):
    """Minimal format: [id|rel] preview — ~20 tokens."""
    rid = r.get("id", "?")[:8]
    rel = r.get("relevance", 0)
    preview = (r.get("preview") or "")[:60]
    return f"[{rid}|{rel:.2f}] {preview}"


def compress_results(results, budget=400):
    """Adaptive compression: compact for few results, minimal for many.

    <=5: all compact
    <=15: top-5 compact, rest minimal
    >15: top-3 compact, next-7 minimal, rest dropped
    """
    if not results:
        return []
    n = len(results)
    compressed = []
    if n <= 5:
        compressed = [compact_result(r) for r in results]
    elif n <= 15:
        for i, r in enumerate(results):
            if i < 5:
                compressed.append(compact_result(r))
            else:
                compressed.append(minimal_result(r))
    else:
        for i, r in enumerate(results):
            if i < 3:
                compressed.append(compact_result(r))
            elif i < 10:
                compressed.append(minimal_result(r))
            else:
                break
    # Trim to budget if needed
    total = sum(estimate_tokens(line) for line in compressed)
    while total > budget and len(compressed) > 1:
        compressed.pop()
        total = sum(estimate_tokens(line) for line in compressed)
    return compressed


def compress_boot_state(state_dict):
    """Single-line boot state: project=X | s#N | feat=X | done=X | next=X."""
    if not state_dict:
        return "state: (empty)"
    parts = []
    if state_dict.get("project"):
        parts.append(f"project={state_dict['project']}")
    if state_dict.get("session_count"):
        parts.append(f"s#{state_dict['session_count']}")
    if state_dict.get("feature"):
        parts.append(f"feat={state_dict['feature']}")
    if state_dict.get("framework_version"):
        parts.append(f"v={state_dict['framework_version']}")
    if state_dict.get("what_was_done"):
        done = state_dict["what_was_done"]
        if len(done) > 120:
            done = done[:120] + "..."
        parts.append(f"done={done}")
    if state_dict.get("next_steps"):
        steps = state_dict["next_steps"]
        if isinstance(steps, list):
            steps = steps[:3]
            parts.append(f"next=[{'; '.join(str(s)[:60] for s in steps)}]")
        else:
            parts.append(f"next={str(steps)[:80]}")
    if state_dict.get("known_issues"):
        issues = state_dict["known_issues"]
        if isinstance(issues, list):
            truncated = [str(s)[:50] for s in issues[:3]]
            parts.append(f"issues=[{'; '.join(truncated)}]")
        else:
            parts.append(f"issues={str(issues)[:80]}")
    return " | ".join(parts)


def compress_postcompact(wm_content, ws_content, dag_summary):
    """Compress post-compact re-injection: trim ops to last 2, one-line DAG.

    Args:
        wm_content: Raw working-memory.md content
        ws_content: Raw working-summary.md content
        dag_summary: DAG summary string (e.g. "branch=main\\n3 branches")

    Returns:
        Compressed string for stdout injection.
    """
    parts = []

    # Working memory: keep header + status + last 2 operations only
    if wm_content and wm_content.strip():
        wm_lines = wm_content.strip().split("\n")
        trimmed = []
        in_ops = False
        ops_collected = []
        for line in wm_lines:
            if line.startswith("## Operations"):
                in_ops = True
                continue
            if in_ops:
                if line.startswith("## ") or line.startswith("# "):
                    # End of operations section — emit last 2
                    in_ops = False
                    if ops_collected:
                        trimmed.append("## Ops (last 2)")
                        trimmed.extend(ops_collected[-2:])
                    trimmed.append(line)
                elif line.startswith("- ["):
                    ops_collected.append(line)
                continue
            # Skip "(awaiting threshold)" lines
            if "awaiting threshold" in line.lower():
                continue
            trimmed.append(line)
        # If ops section was last (no trailing ##)
        if in_ops and ops_collected:
            trimmed.append("## Ops (last 2)")
            trimmed.extend(ops_collected[-2:])
        if trimmed:
            parts.append("\n".join(trimmed))

    # Working summary: only include if non-empty and not awaiting
    if ws_content and ws_content.strip():
        ws_clean = ws_content.strip()
        if "awaiting threshold" not in ws_clean.lower():
            parts.append(ws_clean)

    # DAG: one-line
    if dag_summary and dag_summary.strip():
        dag_line = dag_summary.strip().replace("\n", " | ")
        parts.append(f"DAG: {dag_line}")

    return "\n".join(parts)
