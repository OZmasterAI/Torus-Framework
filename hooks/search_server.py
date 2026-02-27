#!/usr/bin/env python3
"""Torus Framework — Search MCP Server

Lightweight MCP server for direct L0/L2 history search.
- terminal_history_search: FTS5 over terminal/conversation history (L2)
- transcript_context: Raw JSONL session transcript retrieval (L0)

Run standalone: python3 search_server.py
Used via MCP: configured in .claude/mcp.json
"""

import functools
import os
import sys
import traceback

from mcp.server.fastmcp import FastMCP

_HOOKS_DIR = os.path.dirname(__file__)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

mcp = FastMCP("search")


def crash_proof(fn):
    """Wrap MCP tool handler so exceptions return error dicts instead of crashing the server."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Search MCP] {fn.__name__} error: {e}\n{tb}", file=sys.stderr)
            return {"error": f"{fn.__name__} failed: {type(e).__name__}: {e}"}
    return wrapper


def _import_search_fts(integration_name: str):
    """Import search_fts from an integration's db.py without module name collision."""
    import importlib.util
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", integration_name, "db.py"
    )
    spec = importlib.util.spec_from_file_location(f"db_{integration_name}", db_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.search_fts


def _import_from_db(integration_name: str, func_name: str):
    """Import a named function from an integration's db.py."""
    import importlib.util
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", integration_name, "db.py"
    )
    spec = importlib.util.spec_from_file_location(f"db_{integration_name}_{func_name}", db_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name)


@mcp.tool()
@crash_proof
def terminal_history_search(query: str, limit: int = 10) -> dict:
    """Search terminal/conversation history via FTS5 full-text search.

    Args:
        query: Search query (FTS5 MATCH syntax). Empty returns no results.
        limit: Max results to return (1-50, default 10).
    """
    if not query or not query.strip():
        return {"results": [], "count": 0, "source": "terminal_fts"}

    limit = max(1, min(50, limit))
    search_fts = _import_search_fts("terminal-history")
    db_path = os.path.join(
        os.path.expanduser("~"), ".claude", "integrations", "terminal-history", "terminal_history.db"
    )
    results = search_fts(db_path, query, limit=limit)
    return {"results": results, "count": len(results), "source": "terminal_fts"}


@mcp.tool()
@crash_proof
def transcript_context(session_id: str, around_timestamp: str = "", window_minutes: int = 10, max_records: int = 30) -> dict:
    """Get raw L0 transcript context from a session's JSONL file.

    Args:
        session_id: Session UUID (matches JSONL filename).
        around_timestamp: ISO timestamp to center window on. Empty returns last records.
        window_minutes: ±minutes around timestamp (default 10).
        max_records: Max records to return (1-50, default 30).
    """
    if not session_id or not session_id.strip():
        return {"error": "session_id is required", "source": "transcript_l0"}

    import json as _json
    _cfg_path = os.path.join(os.path.expanduser("~"), ".claude", "config.json")
    try:
        with open(_cfg_path) as _cf:
            _cfg = _json.load(_cf)
        if not _cfg.get("transcript_l0", False):
            return {"disabled": True, "source": "transcript_l0",
                    "hint": "Enable with transcript_l0: true in config.json"}
    except Exception:
        pass

    max_records = max(1, min(50, max_records))
    window_minutes = max(1, min(60, window_minutes))
    get_window = _import_from_db("terminal-history", "get_raw_transcript_window")
    return get_window(session_id, around_timestamp=around_timestamp,
                      window_minutes=window_minutes, max_records=max_records)


if __name__ == "__main__":
    mcp.run()
