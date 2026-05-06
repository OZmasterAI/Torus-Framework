#!/usr/bin/env python3
"""Migrate project-tagged memories from DB=main to project-specific databases.

Scans all records in the global knowledge table, extracts project:X tags,
and copies matching records to per-project SurrealDB databases.

Records are COPIED, not moved -- they remain in DB=main as global knowledge.

Usage:
    python3 migrate_project_memories.py --dry-run   # preview only
    python3 migrate_project_memories.py              # actually copy
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))


def main():
    parser = argparse.ArgumentParser(description="Migrate project memories")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be migrated without writing",
    )
    args = parser.parse_args()

    from surrealdb import Surreal

    url = os.environ.get("SURREAL_URL", "ws://127.0.0.1:8822")
    creds = {
        "username": os.environ.get("SURREAL_USER", "root"),
        "password": os.environ.get("SURREAL_PASS", "root"),
    }

    db = Surreal(url)
    db.signin(creds)
    db.use("memory", "main")

    rows = db.query("SELECT * FROM knowledge")
    if not rows or not isinstance(rows, list):
        print("No records found in knowledge table")
        db.close()
        return

    project_re = re.compile(r"project:([^,\s]+)")
    project_records: dict[str, list] = {}

    for row in rows:
        tags = row.get("tags", "") or ""
        match = project_re.search(tags)
        if match:
            proj = match.group(1)
            project_records.setdefault(proj, []).append(row)

    # Detect submodule-specific records for shared DBs
    from boot_pkg.util import parse_gitmodules

    subs = parse_gitmodules(os.path.expanduser("~/.claude"))
    sub_keywords = {}
    for local_path, repo_name in subs.items():
        sub_keywords[local_path] = f"shared.{repo_name}"
        sub_keywords[repo_name] = f"shared.{repo_name}"

    shared_records: dict[str, list] = {}
    for row in rows:
        tags = row.get("tags", "") or ""
        content = row.get("content", "") or ""
        for keyword, db_name in sub_keywords.items():
            if keyword in tags or keyword in content:
                shared_records.setdefault(db_name, []).append(row)
                break

    print(f"Total records in DB=main: {len(rows)}")
    print(
        f"Records with project: tags: {sum(len(v) for v in project_records.values())}"
    )
    print(f"Unique projects: {len(project_records)}")
    for proj, recs in sorted(project_records.items()):
        print(f"  project:{proj} -> {len(recs)} records")
    print(f"Shared DB candidates: {sum(len(v) for v in shared_records.values())}")
    for sdb, recs in sorted(shared_records.items()):
        print(f"  {sdb} -> {len(recs)} records")

    if args.dry_run:
        print("\n[DRY RUN] No records copied.")
        db.close()
        return

    from shared.surreal_collection import init_surreal_db
    from memory_server import _embed_text, _embed_texts, _EMBEDDING_DIM

    copied = 0
    for proj, recs in project_records.items():
        proj_conn = Surreal(url)
        proj_conn.signin(creds)
        proj_conn.use("memory", proj)
        init_surreal_db(
            proj_conn,
            embed_text=_embed_text,
            embed_texts=_embed_texts,
            embedding_dim=_EMBEDDING_DIM,
        )
        for rec in recs:
            rec_id = str(rec.get("id", "")).replace("knowledge:", "")
            if not rec_id:
                continue
            existing = proj_conn.query(
                "SELECT id FROM knowledge WHERE id = $id",
                {"id": f"knowledge:{rec_id}"},
            )
            if existing:
                continue
            insert_data = {k: v for k, v in rec.items() if k != "id"}
            insert_data["migrated_from"] = "main"
            proj_conn.query(
                "CREATE type::record('knowledge', $kid) CONTENT $data",
                {"kid": rec_id, "data": insert_data},
            )
            copied += 1
        proj_conn.close()
        print(f"  Copied {len(recs)} records to DB={proj}")

    # Copy shared DB records
    shared_copied = 0
    for sdb_name, recs in shared_records.items():
        s_conn = Surreal(url)
        s_conn.signin(creds)
        s_conn.use("memory", sdb_name)
        init_surreal_db(
            s_conn,
            embed_text=_embed_text,
            embed_texts=_embed_texts,
            embedding_dim=_EMBEDDING_DIM,
        )
        for rec in recs:
            rec_id = str(rec.get("id", "")).replace("knowledge:", "")
            if not rec_id:
                continue
            existing = s_conn.query(
                "SELECT id FROM knowledge WHERE id = $id",
                {"id": f"knowledge:{rec_id}"},
            )
            if existing:
                continue
            insert_data = {k: v for k, v in rec.items() if k != "id"}
            insert_data["migrated_from"] = "main"
            s_conn.query(
                "CREATE type::record('knowledge', $kid) CONTENT $data",
                {"kid": rec_id, "data": insert_data},
            )
            shared_copied += 1
        s_conn.close()
        print(f"  Copied {len(recs)} records to DB={sdb_name}")

    db.close()
    print(
        f"\nMigration complete: {copied} project records + {shared_copied} shared records"
    )


if __name__ == "__main__":
    main()
