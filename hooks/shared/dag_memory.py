#!/usr/bin/env python3
"""DAG ↔ Memory bridge — bidirectional wiring between conversation DAG and memory.

Phase 2 Tasks 12, 13, 14, 15, 16:
- Auto-extract learnings from assistant responses → remember_this()
- Post-compaction summary → saved to memory
- Fix chains tagged with dag_branch + dag_node
- build_summary() enriched by memory queries
- dag_node tags on memory entries (reverse link)

All functions are fail-open. Import errors and exceptions are caught.

Dual-write to memory server disabled — DAG stores locally in SQLite only.
"""

import json
import os
import re
import sys
import time
from itertools import combinations

# Dual-write enabled — DAG writes to both SQLite and memory server
_DUAL_WRITE = True

# Heuristic patterns for extracting learnings from assistant messages
_LEARNING_PATTERNS = [
    re.compile(r"\b(fix|fixed|resolved|solution|root cause)\b", re.IGNORECASE),
    re.compile(r"\b(decision|chose|choosing|decided|went with)\b", re.IGNORECASE),
    re.compile(r"\b(correction|actually|wrong|mistake|should be)\b", re.IGNORECASE),
    re.compile(r"\b(discovered|found that|turns out|TIL|learned)\b", re.IGNORECASE),
    re.compile(r"\b(pattern|anti-pattern|best practice|gotcha)\b", re.IGNORECASE),
    re.compile(r"\b(bug|bugs|bugfix|defect|regression)\b", re.IGNORECASE),
]

# Stronger signals warrant extraction regardless of throttle
_STRONG_SIGNAL_PATTERNS = [
    re.compile(r"\broot cause\b", re.IGNORECASE),
    re.compile(
        r"\b(critical|important|key)\s+(fix|bug|decision|discovery|learning)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(never|always|must|should not)\b.{0,60}\b(because|due to|since)\b",
        re.IGNORECASE,
    ),
]

# Entity extraction: error classes, file paths, module names, identifiers
_ENTITY_PATTERNS = [
    # Python/code identifiers ending in common suffixes (CamelCase)
    re.compile(
        r"\b([A-Z][a-zA-Z]{3,}(?:Error|Exception|Manager|Handler|Config|Client|Server|Runner))\b"
    ),
    # File paths (relative or absolute with extension)
    re.compile(
        r"(?:^|[\s\(])((?:\./|/)?[\w/.-]+\.(?:py|js|ts|sh|json|yaml|toml|md))\b"
    ),
    # Function/method calls: word( pattern
    re.compile(r"\b([a-z_][a-z0-9_]{3,})\s*\("),
    # Module imports
    re.compile(r"\bfrom\s+([\w.]+)\s+import\b|\bimport\s+([\w.]+)\b"),
]

# Stop-words for entity filtering
_ENTITY_STOPWORDS = {
    "that",
    "this",
    "with",
    "from",
    "into",
    "have",
    "been",
    "will",
    "would",
    "could",
    "should",
    "their",
    "there",
    "these",
    "those",
    "about",
    "which",
    "when",
    "then",
    "also",
    "each",
    "some",
    "more",
    "other",
    "print",
    "return",
    "raise",
    "class",
    "async",
    "await",
    "true",
    "false",
    "none",
}

# Throttle: track assistant node count per session+branch to limit extraction
# Structure: {session_id: {branch_id: count}}
_assistant_node_counts = {}
_EXTRACT_EVERY_N = 5  # Extract at most 1 per 5 assistant nodes


def _has_learning_signal(content):
    """Check if assistant content contains extractable learning signals."""
    return any(p.search(content) for p in _LEARNING_PATTERNS)


def _has_strong_signal(content):
    """Check if content has a high-priority learning signal bypassing throttle."""
    return any(p.search(content) for p in _STRONG_SIGNAL_PATTERNS)


def _extract_entities(content):
    """Extract key entities (error types, file names, module names, identifiers).

    Returns a deduplicated list of entity strings, lowercased, sorted by length desc.
    """
    entities = set()
    for pat in _ENTITY_PATTERNS:
        for m in pat.finditer(content):
            for g in m.groups():
                if g and len(g) > 3 and g.lower() not in _ENTITY_STOPWORDS:
                    entities.add(g.strip().lower())
    return sorted(entities, key=len, reverse=True)[:10]


def _score_content(content):
    """Score content for learning value (0.0 - 1.0).

    Higher scores = more worth saving.
    """
    if len(content) < 80:
        return 0.0
    score = 0.0
    # Pattern density
    matches = sum(1 for p in _LEARNING_PATTERNS if p.search(content))
    score += min(0.6, matches * 0.15)
    # Strong signal boost
    if _has_strong_signal(content):
        score += 0.3
    # Entity richness
    entities = _extract_entities(content)
    score += min(0.1, len(entities) * 0.02)
    return min(1.0, score)


def _truncate(text, max_len=500):
    return text[:max_len] if len(text) > max_len else text


def on_node_added_extract(data):
    """DAG hook handler: auto-extract learnings from assistant responses (Task 12).

    Registered on ON_NODE_ADDED. Fires remember_this() via memory socket
    when an assistant message contains learning signals.
    """
    if not _DUAL_WRITE:
        return
    if data.get("role") != "assistant":
        return

    session_id = data.get("session_id", "main")
    branch_id = data.get("branch_id", "default")

    # Session-keyed throttle tracking: {session_id: {branch_id: count}}
    if session_id not in _assistant_node_counts:
        _assistant_node_counts[session_id] = {}
    session_counts = _assistant_node_counts[session_id]
    session_counts[branch_id] = session_counts.get(branch_id, 0) + 1

    try:
        from shared.dag import get_session_dag

        dag = get_session_dag()
        node = dag.get_node(data.get("node_id", ""))
        if not node:
            return
        content = node["content"]
        if not _has_learning_signal(content):
            return

        # Throttle unless a strong signal overrides
        count = session_counts[branch_id]
        if count % _EXTRACT_EVERY_N != 0 and not _has_strong_signal(content):
            return

        score = _score_content(content)
        if score < 0.1:
            return

        entities = _extract_entities(content)
        entity_tag = (",entities:" + "+".join(entities[:5])) if entities else ""

        from shared.memory_socket import remember

        remember(
            content=_truncate(content, 600),
            context=(
                f"auto-extracted from DAG node {node['id']} on branch "
                f"{data.get('branch_id', '')} (session={session_id}, score={score:.2f})"
            ),
            tags=(
                f"type:auto-captured,dag_node:{node['id']},"
                f"dag_branch:{data.get('branch_id', '')}"
                f"{entity_tag}"
            ),
        )
    except Exception:
        pass  # Fail-open


def save_compaction_summary(session_id="main"):
    """Save current DAG summary to memory as compaction snapshot (Task 13).

    Called from post_compact.py after build_summary(). Includes branch stats,
    active topic entities, recent learning node count, and a snippet from the
    last notable assistant message.
    """
    if not _DUAL_WRITE:
        return
    try:
        from shared.dag import get_session_dag
        from shared.memory_socket import remember

        dag = get_session_dag(session_id)
        summary = dag.build_summary(max_nodes=15)
        if not summary or len(summary) < 50:
            return
        info = dag.current_branch_info()

        # Build enriched context
        context_parts = [
            "pre-compaction snapshot",
            f"session={session_id}",
            f"branch={info['name']}",
            f"branch_id={info['branch_id']}",
            f"messages={info['msg_count']}",
        ]

        # Count assistant vs user nodes in recent history for density hint
        try:
            ancestors = dag.get_ancestors(dag.get_head(), limit=20)
            a_count = sum(1 for n in ancestors if n.get("role") == "assistant")
            u_count = sum(1 for n in ancestors if n.get("role") == "user")
            context_parts.append(f"recent_nodes=a{a_count}/u{u_count}")
        except Exception:
            pass

        # Extract dominant entities from summary for tags
        entity_tags = ""
        try:
            entities = _extract_entities(summary)
            if entities:
                entity_tags = ",entities:" + "+".join(entities[:6])
        except Exception:
            pass

        # Find learning/fix nodes in recent history and append a snippet
        learning_snippet = ""
        try:
            ancestors = dag.get_ancestors(dag.get_head(), limit=30)
            fix_nodes = [
                n
                for n in ancestors
                if n.get("role") == "assistant"
                and _has_learning_signal(n.get("content", ""))
            ]
            if fix_nodes:
                context_parts.append(f"learning_nodes={len(fix_nodes)}")
                snippet = _truncate(fix_nodes[-1].get("content", ""), 120)
                learning_snippet = f"\nRecent learning: {snippet}"
        except Exception:
            pass

        full_content = _truncate(summary + learning_snippet, 750)
        context_str = ", ".join(context_parts)

        remember(
            content=full_content,
            context=context_str,
            tags=(
                f"type:compaction-summary,dag_branch:{info['branch_id']},"
                f"session:{session_id}{entity_tags}"
            ),
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
    Also fires Hebbian co-retrieval boosting via knowledge_graph.add_edge()
    for all pairs of memory IDs returned together.
    """
    if not _DUAL_WRITE:
        return summary
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

        hits = result["results"][:3]

        # Hebbian co-retrieval: strengthen edges between all pairs of retrieved nodes
        try:
            hit_ids = [h.get("id") for h in hits if h.get("id")]
            if len(hit_ids) >= 2:
                from shared.knowledge_graph import KnowledgeGraph

                kg = KnowledgeGraph()
                for id_a, id_b in combinations(hit_ids, 2):
                    kg.add_edge(id_a, id_b, relation_type="co_retrieved", strength=0.1)
                kg.close()
        except Exception:
            pass  # Fail-open: Hebbian boost is non-critical

        # Append memory hits to summary
        memory_lines = ["\n--- related memory ---"]
        for hit in hits:
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
