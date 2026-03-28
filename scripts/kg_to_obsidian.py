#!/usr/bin/env python3
"""Export knowledge graph entities to Obsidian vault as interconnected notes.

Builds entity-to-entity edges by running co-occurrence extraction on
LanceDB memories, then writes vault notes with wikilinks.
Projects become hub nodes via entity-to-project mapping from memory tags.
"""

import os
import re
import sys
import time
import logging

sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))

from shared.knowledge_graph import KnowledgeGraph  # noqa: E402
from shared.entity_extraction import extract_entities  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

MEMORY_DIR = os.path.expanduser("~/data/memory")
KG_PATH = os.path.join(MEMORY_DIR, "knowledge_graph.db")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
VAULT_DIR = os.path.expanduser("~/vault")
GRAPH_DIR = os.path.join(VAULT_DIR, "knowledge-graph")

TYPE_DIRS = {
    "Technology": "technologies",
    "Concept": "concepts",
    "File": "files",
    "Keyword": "keywords",
}

SKIP_ENTITIES = frozenset(
    [
        "Session",
        "Open",
        "Key",
        "Code",
        "User",
        "Deep",
        "Research",
        "Core",
        "Shared",
        "File",
        "Shell",
        "Gate",
        "Persistent",
        "Instance",
        "Role",
        "TBD",
        "Main",
        "New",
        "Set",
        "Run",
        "Test",
        "Type",
        "Data",
        "Node",
        "Path",
        "Line",
        "Name",
        "True",
        "False",
        "None",
        "Default",
        "Value",
        "String",
        "List",
        "Dict",
        "Error",
        "Result",
        "Output",
        "Input",
        "Start",
        "Stop",
        "Check",
        "Config",
        "State",
        "Table",
        "Query",
        "Count",
        "Index",
        "Model",
        "Hook",
        "Tool",
        "/.claude",
    ]
)

MIN_MENTIONS = 3

_PROJECT_TAG_MAP = {
    "torus-web": "torus-web",
    "torus-framework": "torus-framework",
    "chainovi": "chainovi",
    "eclipse-agave": "eclipse-agave",
    "trading-framework": "trading-framework",
    "pcfix": "pcfix",
    "zerobrain": "zerobrain",
    "go_sdk_agent": "go-sdk-agent",
    "go-sdk-agent": "go-sdk-agent",
    "torus-voice-ios": "torus-voice-ios",
    "tap": "tap-project",
    "TRv1": "trv1",
    "Open-Pi-Torus": "openTorus",
    "torus-tui": "torus-tui",
    "torus-pi-agent": "torus-pi-agent",
    "ts-sdk-agent": "ts-sdk-agent",
    ".claude": "torus-framework",
    "research": "research-project",
    "framework-v5": "framework-v5",
    "branch-writing": "branch-writing",
}

_ALIASES = {
    "torus": "torus-framework",
    "lancedb": "lance-db",
    "chromadb": "chroma-db",
    "memory system": "memory-system",
    "memory server": "memory-server",
    "circuit breaker": "circuit-breaker",
    "knowledge graph": "knowledge-graph",
    "causal chain": "causal-chain",
    "claude code": "claude-code",
    "bubble tea": "bubble-tea",
    "git worktree": "git-worktrees",
    "spreading activation": "knowledge-graph-spreading-activation",
    "gate result": "gate-result",
    "hook system": "hook-system",
    "ltp tracker": "ltp-tracker",
    "vector search": "vector-search",
    "context management": "context-management",
}


def sanitize_filename(name):
    safe = re.sub(r'[<>:"/\\|?*]', "", name)
    safe = safe.strip(". ")
    return safe or "unnamed"


def _extract_projects(tags_str):
    projects = set()
    for m in re.finditer(r"project:([^\s,]+)", tags_str):
        if m.group(1) in _PROJECT_TAG_MAP:
            projects.add(_PROJECT_TAG_MAP[m.group(1)])
    for m in re.finditer(r"subproject:([^\s,]+)", tags_str):
        if m.group(1) in _PROJECT_TAG_MAP:
            projects.add(_PROJECT_TAG_MAP[m.group(1)])
    for t in tags_str.split(","):
        t = t.strip()
        if t in _PROJECT_TAG_MAP:
            projects.add(_PROJECT_TAG_MAP[t])
    return projects


def _process_memory_row(row, entities_by_name, edge_weights, entity_projects):
    """Process one memory row: extract entities, co-occurrences, project links."""
    content = str(row.get("content", ""))
    context = str(row.get("context", ""))
    tags = str(row.get("tags", ""))
    text = content + " " + context + " " + tags

    projects = _extract_projects(tags)
    ents = extract_entities(text)
    names = sorted(set(e["name"] for e in ents if e["name"] in entities_by_name))

    for name in names:
        for proj in projects:
            ep = entity_projects.setdefault(name, {})
            ep[proj] = ep.get(proj, 0) + 1

    for j, a in enumerate(names):
        for b in names[j + 1 :]:
            pair = (min(a, b), max(a, b))
            edge_weights[pair] = edge_weights.get(pair, 0) + 1


def build_entity_edges(entities_by_name):
    import lancedb

    db = lancedb.connect(LANCE_DIR)
    table = db.open_table("knowledge")
    rows = table.to_pandas()

    edge_weights = {}
    entity_projects = {}
    total = len(rows)
    log.info("Scanning %d memories for co-occurrences + project mapping...", total)

    for idx in range(total):
        _process_memory_row(
            rows.iloc[idx], entities_by_name, edge_weights, entity_projects
        )
        if (idx + 1) % 1000 == 0:
            log.info("  %d/%d...", idx + 1, total)

    edges = {pair: count for pair, count in edge_weights.items() if count >= 2}
    proj_link_count = sum(len(v) for v in entity_projects.values())
    log.info(
        "Found %d entity-entity edges, %d entity-project links",
        len(edges),
        proj_link_count,
    )
    return edges, entity_projects


def _build_vault_index():
    index = {}
    for dirpath, _, files in os.walk(VAULT_DIR):
        if "knowledge-graph" in dirpath:
            continue
        for f in files:
            if f.endswith(".md"):
                stem = f[:-3]
                index[stem.lower()] = stem
                index[stem.lower().replace("-", " ")] = stem
                index[stem.lower().replace("-", "_")] = stem
    return index


_VAULT_INDEX = None


def find_existing_note(entity_name):
    global _VAULT_INDEX
    if _VAULT_INDEX is None:
        _VAULT_INDEX = _build_vault_index()

    lower = entity_name.lower()
    if lower in _ALIASES:
        return _ALIASES[lower]
    for variant in [
        lower,
        lower.replace("_", "-"),
        lower.replace(" ", "-"),
        lower.replace("-", "_"),
        lower.replace("_", " "),
    ]:
        if variant in _VAULT_INDEX:
            return _VAULT_INDEX[variant]
    return None


def write_vault_note(entity, neighbors, projects, out_dir):
    name = entity["name"]
    etype = entity["type"]
    mentions = entity["mention_count"]
    subdir = os.path.join(out_dir, TYPE_DIRS.get(etype, "other"))
    os.makedirs(subdir, exist_ok=True)

    filepath = os.path.join(subdir, sanitize_filename(name) + ".md")
    existing = find_existing_note(name)
    proj_links = sorted(projects.items(), key=lambda x: -x[1]) if projects else []

    lines = [
        "---",
        "type: " + etype.lower(),
        "mentions: " + str(mentions),
        "source: knowledge-graph",
    ]
    if proj_links:
        lines.append("projects:")
        for proj, _ in proj_links:
            lines.append('  - "[[' + proj + ']]"')
    lines.extend(
        ["tags: [auto-generated, knowledge-graph]", "---", "", "# " + name, ""]
    )

    if existing:
        lines.extend(["See also: [[" + existing + "]]", ""])

    if proj_links:
        lines.append("## Projects")
        for proj, count in proj_links:
            lines.append("- [[" + proj + "]] (" + str(count) + "x)")
        lines.append("")

    if neighbors:
        lines.append("## Related")
        for neighbor_name, count in sorted(neighbors, key=lambda x: -x[1]):
            lines.append(
                "- [[" + sanitize_filename(neighbor_name) + "]] (" + str(count) + "x)"
            )
        lines.append("")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))


def _load_entities():
    import sqlite3

    conn = sqlite3.connect(KG_PATH)
    rows = conn.execute(
        "SELECT name, type, mention_count, salience FROM entities "
        "WHERE mention_count >= ? ORDER BY mention_count DESC",
        (MIN_MENTIONS,),
    ).fetchall()
    conn.close()

    entities = {}
    for name, etype, mentions, salience in rows:
        if name in SKIP_ENTITIES or len(name) <= 2:
            continue
        if re.match(r"^[0-9a-f]{8,}$", name):
            continue
        entities[name] = {
            "name": name,
            "type": etype,
            "mention_count": mentions,
            "salience": salience,
        }
    return entities


def _write_moc(entities_by_name, edges):
    moc_path = os.path.join(GRAPH_DIR, "_knowledge-graph.md")
    with open(moc_path, "w") as f:
        f.write("---\ntype: moc\ntags: [knowledge-graph, auto-generated]\n---\n\n")
        f.write("# Knowledge Graph\n\n")
        f.write(
            "Auto-generated from "
            + str(len(entities_by_name))
            + " entities and "
            + str(len(edges))
            + " edges.\n\n"
        )

        for etype in ["Technology", "Concept", "Keyword", "File"]:
            typed = [(n, e) for n, e in entities_by_name.items() if e["type"] == etype]
            if not typed:
                continue
            typed.sort(key=lambda x: -x[1]["mention_count"])
            f.write("## " + etype + " (" + str(len(typed)) + ")\n")
            for name, ent in typed[:30]:
                f.write(
                    "- [["
                    + sanitize_filename(name)
                    + "]] ("
                    + str(ent["mention_count"])
                    + "x)\n"
                )
            if len(typed) > 30:
                f.write("- ... and " + str(len(typed) - 30) + " more\n")
            f.write("\n")


def main():
    t0 = time.monotonic()
    kg = KnowledgeGraph(KG_PATH)

    entities_by_name = _load_entities()
    log.info("Exporting %d entities", len(entities_by_name))

    edges, entity_projects = build_entity_edges(entities_by_name)

    neighbors = {}
    for (a, b), count in edges.items():
        neighbors.setdefault(a, []).append((b, count))
        neighbors.setdefault(b, []).append((a, count))

    os.makedirs(GRAPH_DIR, exist_ok=True)
    written = 0
    for name, entity in entities_by_name.items():
        write_vault_note(
            entity, neighbors.get(name, []), entity_projects.get(name, {}), GRAPH_DIR
        )
        written += 1

    _write_moc(entities_by_name, edges)

    elapsed = time.monotonic() - t0
    log.info("Done in %.1fs — %d notes, %d edges", elapsed, written, len(edges))
    kg.close()


if __name__ == "__main__":
    main()
