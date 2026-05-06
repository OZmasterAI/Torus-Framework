#!/usr/bin/env python3
"""Backfill project:torus-framework tag on untagged framework records.

Strong-signal heuristics only (no session-NNN — too broad):
- area:framework
- area:memory-system
- gate-XX (any gate reference)
- hook/enforcer/shim keywords
- test_framework keyword
- torus-framework keyword (without project: prefix)

Records already tagged with any project:X are skipped.

Usage:
    python3 backfill_framework_tags.py --dry-run
    python3 backfill_framework_tags.py
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from surrealdb import Surreal

    url = os.environ.get("SURREAL_URL", "ws://127.0.0.1:8822")
    db = Surreal(url)
    db.signin(
        {
            "username": os.environ.get("SURREAL_USER", "root"),
            "password": os.environ.get("SURREAL_PASS", "root"),
        }
    )
    db.use("memory", "main")

    rows = db.query("SELECT id, tags FROM knowledge")
    project_re = re.compile(r"project:([^,\s]+)")

    def has_framework_signal(tags):
        return (
            "area:framework" in tags
            or "area:memory-system" in tags
            or bool(re.search(r"gate[-_]\d", tags))
            or any(k in tags for k in ("hook", "enforcer", "shim", "test_framework"))
            or ("torus-framework" in tags and "project:" not in tags)
        )

    untagged = [r for r in rows if not project_re.search(r.get("tags", "") or "")]
    matches = [r for r in untagged if has_framework_signal(r.get("tags", "") or "")]

    print(f"Total records: {len(rows)}")
    print(f"Untagged (no project:X): {len(untagged)}")
    print(f"Framework signal matches: {len(matches)}")

    if args.dry_run:
        print("\n[DRY RUN] No records modified.")
        db.close()
        return

    updated = 0
    for r in matches:
        rid = str(r.get("id", ""))
        old_tags = r.get("tags", "") or ""
        new_tags = (
            f"{old_tags},project:torus-framework"
            if old_tags
            else "project:torus-framework"
        )
        db.query(f"UPDATE {rid} SET tags = $tags", {"tags": new_tags})
        updated += 1

    db.close()
    print(f"\nBackfill complete: {updated} records tagged project:torus-framework")


if __name__ == "__main__":
    main()
