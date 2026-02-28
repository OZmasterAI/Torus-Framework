"""Dead rules detector for the Torus framework.

Validates ~/.claude/rules/*.md for dead globs, broken path refs, and overlaps.
Global rules globs are advisory — rules load project-wide regardless of globs.

Public API: validate_rules(rules_dir=None, base_dir=None) -> dict
    {"total", "valid", "dead", "issues", "overlaps", "suggestions"}
"""

import fnmatch
import os
import re

_HOME = os.path.expanduser("~")
_CLAUDE_DIR = os.path.join(_HOME, ".claude")
_DEFAULT_RULES_DIR = os.path.join(_CLAUDE_DIR, "rules")

_GLOB_NOTE = "global rules/ globs are advisory — rule loads project-wide regardless"


def _parse_frontmatter(content):
    if not content.startswith("---"):
        return {}, ["No frontmatter block"]
    end = content.find("\n---", 3)
    if end == -1:
        return {}, ["Frontmatter block not closed"]
    fields = {}
    for line in content[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, []


def _walk_files(base_dir):
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            yield os.path.relpath(os.path.join(root, f), base_dir)


def _glob_matches_any(pattern, base_dir):
    pat = pattern.strip().removeprefix(".claude/")
    prefix = pat.split("**")[0].rstrip("/") if "**" in pat else None
    for rel in _walk_files(base_dir):
        if fnmatch.fnmatch(rel, pat) or (prefix and rel.startswith(prefix)):
            return True
    return False


def _extract_doc_paths(content, claude_dir):
    """Return (raw, exists) for backtick paths with '/' that look like file refs."""
    refs = []
    for m in re.finditer(r'`([^`]+\.(?:md|py|json))`', content):
        raw = m.group(1)
        if " " in raw or raw.startswith(("from ", "@")) or "/" not in raw:
            continue
        resolved = (os.path.expanduser(raw) if raw.startswith(("/", "~"))
                    else os.path.join(claude_dir, raw.lstrip("./")))
        refs.append((raw, os.path.exists(resolved)))
    return refs


def _detect_overlaps(rules_globs):
    overlaps = []
    names = list(rules_globs.keys())
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for ga in rules_globs[a]:
                for gb in rules_globs[b]:
                    ga_n, gb_n = ga.removeprefix(".claude/"), gb.removeprefix(".claude/")
                    if "**" in gb_n and fnmatch.fnmatch(ga_n, gb_n):
                        overlaps.append(f"{b}:'{gb}' subsumes {a}:'{ga}'")
                    elif "**" in ga_n and fnmatch.fnmatch(gb_n, ga_n):
                        overlaps.append(f"{a}:'{ga}' subsumes {b}:'{gb}'")
    return overlaps


def validate_rules(rules_dir=None, base_dir=None):
    """Scan rules/ for dead globs, broken path refs, overlaps. Returns health report."""
    rules_dir = os.path.abspath(os.path.expanduser(rules_dir or _DEFAULT_RULES_DIR))
    base_dir = os.path.abspath(os.path.expanduser(base_dir or _CLAUDE_DIR))
    report = {"total": 0, "valid": [], "dead": [], "issues": {}, "overlaps": [], "suggestions": []}

    if not os.path.isdir(rules_dir):
        report["issues"]["<rules_dir>"] = [f"Rules directory not found: {rules_dir}"]
        return report

    rule_files = sorted(f for f in os.listdir(rules_dir) if f.endswith(".md"))
    report["total"] = len(rule_files)
    rules_globs = {}

    for fname in rule_files:
        fpath = os.path.join(rules_dir, fname)
        errors = []
        try:
            content = open(fpath, encoding="utf-8").read()
        except OSError as e:
            report["issues"][fname] = [f"Cannot read: {e}"]
            continue

        fields, fm_errors = _parse_frontmatter(content)
        errors.extend(fm_errors)

        globs_raw = fields.get("globs", "")
        glob_list = [g.strip() for g in globs_raw.split(",") if g.strip()]
        rules_globs[fname] = glob_list

        if not glob_list and not fm_errors:
            errors.append(f"No globs: field — {_GLOB_NOTE}")
            report["suggestions"].append(f"{fname}: add globs for documentation clarity")
        elif glob_list:
            errors.append(f"INFO: {_GLOB_NOTE}")

        dead = [g for g in glob_list if not _glob_matches_any(g, base_dir)]
        if dead:
            label = "All" if len(dead) == len(glob_list) else "Some"
            if label == "All":
                report["dead"].append(fname)
            errors.append(f"{label} globs match no files: {dead}")
            report["suggestions"].append(f"{fname}: fix or remove dead globs: {dead}")

        for raw, exists in _extract_doc_paths(content, base_dir):
            if not exists:
                errors.append(f"Broken path reference: `{raw}`")

        # Filter out pure INFO messages for valid determination
        real_errors = [e for e in errors if not e.startswith("INFO:")]
        if real_errors:
            report["issues"][fname] = errors
        else:
            report["valid"].append(fname)

    report["overlaps"] = _detect_overlaps(rules_globs)
    if report["overlaps"]:
        report["suggestions"].append("Consolidate overlapping rules to reduce redundant loading")
    if report["dead"]:
        report["suggestions"].append(f"Review dead rules (all globs match nothing): {report['dead']}")
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(validate_rules(), indent=2))
