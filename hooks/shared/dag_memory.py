#!/usr/bin/env python3
"""DAG ↔ Memory bridge — bidirectional wiring between conversation DAG and memory.

Phase 2 Tasks 12, 13, 14, 15, 16:
- Auto-extract learnings from assistant responses → remember_this()
- Post-compaction summary → saved to memory
- Fix chains tagged with dag_branch + dag_node
- build_summary() enriched by memory queries
- dag_node tags on memory entries (reverse link)

All functions are fail-open. Import errors and exceptions are caught.
"""

import json
import os
import re
import sys
import time

# Heuristic patterns for extracting learnings from assistant messages
_LEARNING_PATTERNS = [
    re.compile(r"\b(fix|fixed|resolved|solution|root cause)\b", re.IGNORECASE),
    re.compile(r"\b(decision|chose|choosing|decided|went with)\b", re.IGNORECASE),
    re.compile(r"\b(correction|actually|wrong|mistake|should be)\b", re.IGNORECASE),
    re.compile(r"\b(discovered|found that|turns out|TIL|learned)\b", re.IGNORECASE),
    re.compile(r"\b(pattern|anti-pattern|best practice|gotcha)\b", re.IGNORECASE),
]

# Throttle: track assistant node count to limit extraction
_assistant_node_count = 0
_EXTRACT_EVERY_N = 5  # Extract at most 1 per 5 assistant nodes


def _has_learning_signal(content):
    """Check if assistant content contains extractable learning signals."""
    return any(p.search(content) for p in _LEARNING_PATTERNS)


def _truncate(text, max_len=500):
    return text[:max_len] if len(text) > max_len else text


def on_node_added_extract(data):
    """DAG hook handler: auto-extract learnings from assistant responses (Task 12).

    Registered on ON_NODE_ADDED. Fires remember_this() via memory socket
    when an assistant message contains learning signals.
    """
    global _assistant_node_count
    if data.get("role") != "assistant":
        return

    _assistant_node_count += 1
    if _assistant_node_count % _EXTRACT_EVERY_N != 0:
        return  # Throttle

    try:
        from shared.dag import get_session_dag

        dag = get_session_dag()
        node = dag.get_node(data.get("node_id", ""))
        if not node:
            return
        content = node["content"]
        if not _has_learning_signal(content):
            return

        from shared.memory_socket import remember

        remember(
            content=_truncate(content, 600),
            context=f"auto-extracted from DAG node {node['id']} on branch {data.get('branch_id', '')}",
            tags=f"type:auto-captured,dag_node:{node['id']},dag_branch:{data.get('branch_id', '')}",
        )
    except Exception:
        pass  # Fail-open


def save_compaction_summary(session_id="main"):
    """Save current DAG summary to memory as compaction snapshot (Task 13).

    Called from post_compact.py after build_summary().
    """
    try:
        from shared.dag import get_session_dag
        from shared.memory_socket import remember

        dag = get_session_dag(session_id)
        summary = dag.build_summary(max_nodes=15)
        if not summary or len(summary) < 50:
            return
        info = dag.current_branch_info()
        remember(
            content=_truncate(summary, 700),
            context=f"pre-compaction snapshot, branch={info['name']}, {info['msg_count']} messages",
            tags=f"type:compaction-summary,dag_branch:{info['branch_id']}",
        )
    except Exception:
        pass  # Fail-open


def get_dag_context_for_chain():
    """Return current DAG branch + head node for fix chain tagging (Task 14)."""
    try:
        from shared.dag import get_session_dag

        dag = get_session_dag()
        return {
            "dag_branch": dag.current_branch_id(),
            "dag_node": dag.get_head(),
        }
    except Exception:
        return {}


def get_dag_head_tag():
    """Return current DAG head node ID for memory entry tagging (Task 16).

    Used by auto_remember and other code that calls remember_this().
    Returns empty string if DAG not available.
    """
    try:
        from shared.dag import get_session_dag

        dag = get_session_dag()
        return dag.get_head()
    except Exception:
        return ""


def enrich_summary_with_memory(summary, session_id="main"):
    """Enrich a DAG summary with related memory hits (Task 15).

    Extracts key topics from the summary, queries memory, appends top hits.
    """
    try:
        from shared.memory_socket import query

        # Extract words >4 chars as topic candidates
        words = set(
            w.lower()
            for w in re.findall(r"\b\w{5,}\b", summary)
            if w.lower()
            not in {
                "assistant",
                "message",
                "about",
                "there",
                "which",
                "should",
                "would",
                "could",
                "their",
                "these",
                "those",
            }
        )
        if not words:
            return summary

        # Query memory with top topics
        topic_query = " ".join(list(words)[:5])
        result = query(topic_query, top_k=3)
        if not result or not result.get("results"):
            return summary

        # Append memory hits
        memory_lines = ["\n--- related memory ---"]
        for hit in result["results"][:3]:
            preview = hit.get("preview", hit.get("content", ""))[:150]
            if preview:
                memory_lines.append(f"  [{hit.get('relevance', 0):.1f}] {preview}")

        if len(memory_lines) > 1:
            return summary + "\n".join(memory_lines)
        return summary
    except Exception:
        return summary  # Fail-open: return original


def register_dag_memory_hooks(dag):
    """Wire DAG memory hooks into a DAG instance.

    Call this after creating/getting a DAG to enable auto-extraction.
    """
    try:
        from shared.dag_hooks import DAGHookRegistry, ON_NODE_ADDED

        hooks = dag._hooks
        if hooks is None:
            hooks = DAGHookRegistry()
            dag.set_hooks(hooks)
        hooks.register(
            ON_NODE_ADDED,
            on_node_added_extract,
            name="memory-extract",
            priority=200,  # Run after other hooks
        )
    except Exception:
        pass  # Fail-open
