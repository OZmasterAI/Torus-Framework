"""Extract code graph summary from toroidal-indexer for session start injection."""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _query_rows(db: Any, sql: str, params: dict | None = None) -> list[dict]:
    result = db.query(sql, params) if params else db.query(sql)
    return result if isinstance(result, list) else []


def extract_graph_context(project_name: str | None) -> str | None:
    """Query the code graph for project summary. Returns compact string or None."""
    if not project_name:
        return None

    try:
        from indexer.schema import connect_code_graph
    except ImportError:
        return None

    try:
        db_name = os.environ.get("INDEXER_DB", "main")
        db = connect_code_graph(database=db_name)

        stats = _query_rows(
            db,
            "SELECT count() AS cnt FROM code_node WHERE project=$proj GROUP ALL",
            {"proj": project_name},
        )
        node_count = stats[0]["cnt"] if stats else 0
        if node_count == 0:
            return None

        file_stats = _query_rows(
            db,
            "SELECT array::distinct(file) AS files FROM code_node WHERE project=$proj GROUP ALL",
            {"proj": project_name},
        )
        file_count = (
            len(file_stats[0]["files"])
            if file_stats and "files" in file_stats[0]
            else 0
        )

        hubs = _query_rows(
            db,
            """
            SELECT name, file, type,
                   count(->calls + <-calls + ->reads + <-reads + ->imports + <-imports) AS degree
            FROM code_node
            WHERE project=$proj
            ORDER BY degree DESC
            LIMIT 8
            """,
            {"proj": project_name},
        )

        if not hubs or all(h.get("degree", 0) == 0 for h in hubs):
            hubs = _query_rows(
                db,
                """
                SELECT name, file, type
                FROM code_node
                WHERE project=$proj AND type IN ['function', 'class', 'export']
                LIMIT 8
                """,
                {"proj": project_name},
            )

        parts = [f"Indexed: {node_count} nodes across {file_count} files"]

        hub_lines = []
        for h in hubs[:8]:
            name = h.get("name", "?")
            file = h.get("file", "?")
            ntype = h.get("type", "?")
            degree = h.get("degree")
            if degree:
                hub_lines.append(f"{name} ({file}, {ntype}, degree:{degree})")
            else:
                hub_lines.append(f"{name} ({file}, {ntype})")

        if hub_lines:
            parts.append("Key hubs: " + " | ".join(hub_lines))

        parts.append(
            "Use run_tool('indexer', 'code_callers'|'code_hubs'|'code_path'|'code_blast_radius', ...) to query the graph"
        )

        return "\n".join(parts)

    except Exception:
        return None
