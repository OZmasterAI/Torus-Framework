#!/usr/bin/env python3
"""PreToolUse hook: inject structural context from Toroidal-Indexer code graph.

Reads Edit/Write tool input, identifies which function is being edited via tree-sitter,
queries SurrealDB for callers/readers, and injects context as additionalContext.
Always exits 0 (fail-open, never blocks).
"""

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

RAMDISK_DIR = f"/run/user/{os.getuid()}/claude-hooks"

_EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".sh": "bash",
    ".bash": "bash",
    ".proto": "proto",
}

_FUNC_NODE_TYPES = {
    "function_definition",
    "function_declaration",
    "function_item",
    "method_definition",
    "method_declaration",
    "arrow_function",
}

_NAME_CHILD_TYPES = {
    "identifier",
    "property_identifier",
    "field_identifier",
    "name",
    "word",
}


def _find_innermost_func(node, target_line):
    """Walk tree-sitter AST to find the innermost function containing target_line (0-indexed)."""
    best = None
    if node.type in _FUNC_NODE_TYPES:
        if node.start_point[0] <= target_line <= node.end_point[0]:
            best = node
    for child in node.children:
        candidate = _find_innermost_func(child, target_line)
        if candidate is not None:
            if best is None or candidate.start_point[0] >= best.start_point[0]:
                best = candidate
    return best


def _get_node_name(node):
    """Extract the function/method name from a tree-sitter node."""
    for child in node.children:
        if child.type in _NAME_CHILD_TYPES:
            return child.text.decode()
    return None


def _identify_function(file_path, old_string):
    """Parse source with tree-sitter to find which function/method contains old_string.

    Supports Python, TypeScript, TSX, JavaScript, Rust, Go, Bash.
    Returns the function name (str) or None.
    """
    ext = os.path.splitext(file_path)[1].lower()
    lang = _EXT_TO_LANG.get(ext)
    if not lang:
        return None
    try:
        from tree_sitter_languages import get_parser
    except ImportError:
        return None
    try:
        source = open(file_path, "rb").read()
    except (OSError, IOError):
        return None
    if old_string.encode() not in source:
        return None

    parser = get_parser(lang)
    tree = parser.parse(source)

    source_lines = source.split(b"\n")
    first_old_line = old_string.splitlines()[0].strip()
    if not first_old_line:
        return None

    target_line = None
    for i, line in enumerate(source_lines):
        if first_old_line.encode() in line:
            target_line = i
            break

    if target_line is None:
        return None

    func_node = _find_innermost_func(tree.root_node, target_line)
    return _get_node_name(func_node) if func_node else None


def _format_caller(c):
    """Format a single caller dict, prefixing with ~ if AI-sourced."""
    prefix = "~" if c.get("confidence", 1.0) < 1.0 else ""
    name = c.get("name", "?")
    fpath = os.path.basename(c.get("file", "?"))
    line = c.get("source_line") or c.get("line", 0)
    return f"{prefix}{name} ({fpath}:L{line})"


def _format_reader(r):
    """Format a single reader dict, prefixing with ~ if AI-sourced."""
    prefix = "~" if r.get("confidence", 1.0) < 1.0 else ""
    name = r.get("name", "?")
    fpath = os.path.basename(r.get("file", "?"))
    line = r.get("line", 0)
    return f"{prefix}{name} ({fpath}:L{line})"


def _load_dedup(session_id):
    """Load the dedup set for this session from ramdisk."""
    path = os.path.join(RAMDISK_DIR, f"indexer_dedup_{session_id}.json")
    try:
        with open(path) as f:
            return set(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _save_dedup(session_id, seen):
    """Save the dedup set for this session to ramdisk."""
    path = os.path.join(RAMDISK_DIR, f"indexer_dedup_{session_id}.json")
    try:
        os.makedirs(RAMDISK_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(list(seen), f)
    except OSError:
        pass


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    event = json.loads(raw)
    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    old_string = tool_input.get("old_string", "")

    if not file_path:
        return

    # Identify which function is being edited
    func_name = _identify_function(file_path, old_string) if old_string else None

    # Session and dedup
    session_id = os.environ.get("TORUS_SESSION_ID") or str(os.getppid())
    dedup_key = f"{file_path}:{func_name}" if func_name else f"{file_path}:__file__"
    seen = _load_dedup(session_id)
    if dedup_key in seen:
        return
    seen.add(dedup_key)

    # Connect to SurrealDB
    from indexer.schema import (
        _node_key,
        connect_code_graph,
        get_callers,
        get_readers,
    )
    from surrealdb import RecordID

    db_name = os.environ.get("INDEXER_DB", "main")
    project = os.environ.get("INDEXER_PROJECT", "")
    db = connect_code_graph(database=db_name)

    parts = []

    if func_name and project:
        # Query callers of this specific function
        node_key = _node_key(project, file_path, func_name)
        node_id = RecordID("code_node", node_key)
        callers = get_callers(db, node_id)
        if callers:
            caller_strs = [_format_caller(c) for c in callers]
            parts.append(
                f"Editing fn:{func_name} -- called by: {', '.join(caller_strs)}"
            )

        # Check if any fields in this function have readers
        # Query file-level field nodes
        fields = db.query(
            "SELECT * FROM code_node WHERE project=$proj AND file=$file AND type='field'",
            {"proj": project, "file": file_path},
        )
        for field in fields:
            fid = field["id"]
            readers = get_readers(db, fid)
            if readers:
                reader_strs = [_format_reader(r) for r in readers]
                parts.append(
                    f"field '{field['name']}' read by: {', '.join(reader_strs)}"
                )
    elif project:
        # File-level fallback: show callers of all functions in the file
        nodes = db.query(
            "SELECT * FROM code_node WHERE project=$proj AND file=$file",
            {"proj": project, "file": file_path},
        )
        for node in nodes:
            nid = node["id"]
            if node.get("type") == "function":
                callers = get_callers(db, nid)
                if callers:
                    caller_strs = [_format_caller(c) for c in callers]
                    parts.append(
                        f"fn:{node['name']} called by: {', '.join(caller_strs)}"
                    )
            elif node.get("type") == "field":
                readers = get_readers(db, nid)
                if readers:
                    reader_strs = [_format_reader(r) for r in readers]
                    parts.append(
                        f"field '{node['name']}' read by: {', '.join(reader_strs)}"
                    )

    if not parts:
        _save_dedup(session_id, seen)
        return

    context_text = " | ".join(parts)
    _save_dedup(session_id, seen)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": context_text,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
