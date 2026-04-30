#!/usr/bin/env python3
"""Export all data from SurrealDB v2 embedded store and import into v3 server.

Usage:
  1. Stop memory_server.py first (releases surrealkv lock)
  2. python3 migrate_v2_to_v3.py export   # dumps to ~/data/memory/v3_migration/
  3. Start SurrealDB v3: surreal start --user root --pass root surrealkv://~/data/memory/surrealdb_v3
  4. python3 migrate_v2_to_v3.py import   # loads into v3 via ws://
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SURREAL_DIR = os.path.expanduser("~/data/memory/surrealdb")
EXPORT_DIR = os.path.expanduser("~/data/memory/v3_migration")
V3_URL = "ws://127.0.0.1:8822"
TABLES = [
    "knowledge",
    "fix_outcomes",
    "observations",
    "web_pages",
    "quarantine",
    "clusters",
]
EDGE_TABLES = ["tried_for", "resolved", "failed_on", "derived_from"]


def export_v2():
    """Read all tables from embedded v2 store and dump to JSON."""
    from surrealdb import Surreal

    os.makedirs(EXPORT_DIR, exist_ok=True)

    print(f"[EXPORT] Opening surrealkv://{SURREAL_DIR}")
    db = Surreal(f"surrealkv://{SURREAL_DIR}")
    db.use("memory", "main")

    total = 0
    for table in TABLES:
        rows = db.query(f"SELECT * FROM {table}")
        rows = rows if rows else []
        count = len(rows)
        total += count

        out_path = os.path.join(EXPORT_DIR, f"{table}.json")
        serialized = []
        for r in rows:
            sr = {}
            for k, v in r.items():
                if hasattr(v, "table_name"):
                    sr[k] = {
                        "_recordid": True,
                        "table": v.table_name,
                        "id": str(v.id),
                    }
                elif hasattr(v, "isoformat"):
                    sr[k] = {"_datetime": True, "value": v.isoformat()}
                else:
                    sr[k] = v
            serialized.append(sr)

        with open(out_path, "w") as f:
            json.dump(serialized, f)
        print(f"  {table}: {count} records → {out_path}")

    for edge in EDGE_TABLES:
        rows = db.query(f"SELECT * FROM {edge}")
        rows = rows if rows else []
        count = len(rows)
        if count > 0:
            total += count
            out_path = os.path.join(EXPORT_DIR, f"edge_{edge}.json")
            serialized = []
            for r in rows:
                sr = {}
                for k, v in r.items():
                    if hasattr(v, "table_name"):
                        sr[k] = {
                            "_recordid": True,
                            "table": v.table_name,
                            "id": str(v.record_id),
                        }
                    elif hasattr(v, "isoformat"):
                        sr[k] = {"_datetime": True, "value": v.isoformat()}
                    else:
                        sr[k] = v
                serialized.append(sr)
            with open(out_path, "w") as f:
                json.dump(serialized, f)
            print(f"  edge:{edge}: {count} records → {out_path}")

    print(f"\n[EXPORT] Done. {total} total records exported to {EXPORT_DIR}")


def import_v3():
    """Load exported JSON into SurrealDB v3 server via websocket."""
    from surrealdb import Surreal, RecordID

    print(f"[IMPORT] Connecting to {V3_URL}")
    db = Surreal(V3_URL)
    db.signin(
        {
            "username": os.environ.get("SURREAL_USER", "root"),
            "password": os.environ.get("SURREAL_PASS", "root"),
        }
    )
    db.use("memory", "main")

    db.query(
        "DEFINE ANALYZER IF NOT EXISTS mem_analyzer "
        "TOKENIZERS blank,class FILTERS lowercase,snowball(english)"
    )

    total = 0
    for table in TABLES:
        json_path = os.path.join(EXPORT_DIR, f"{table}.json")
        if not os.path.exists(json_path):
            print(f"  {table}: SKIP (no export file)")
            continue

        with open(json_path) as f:
            rows = json.load(f)

        if not rows:
            print(f"  {table}: 0 records")
            continue

        count = 0
        batch_size = 50
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            for row in batch:
                rid = row.pop("id", None)
                if rid and isinstance(rid, dict) and rid.get("_recordid"):
                    doc_id = rid["id"]
                else:
                    doc_id = str(rid) if rid else None

                for k, v in list(row.items()):
                    if isinstance(v, dict) and v.get("_recordid"):
                        row[k] = RecordID(v["table"], v["id"])
                    elif isinstance(v, dict) and v.get("_datetime"):
                        row[k] = v["value"]

                if doc_id:
                    safe_id = str(doc_id).replace("'", "")
                    set_parts = []
                    params = {}
                    for k, v in row.items():
                        pname = f"p_{k}"
                        params[pname] = v
                        set_parts.append(f"{k} = ${pname}")
                    if set_parts:
                        sql = f"UPSERT {table}:`{safe_id}` SET " + ", ".join(set_parts)
                        try:
                            db.query(sql, params)
                            count += 1
                        except Exception as e:
                            print(f"    ERR on {table}:{safe_id}: {e}")
                else:
                    params = {f"p_{k}": v for k, v in row.items()}
                    set_parts = [f"{k} = $p_{k}" for k in row]
                    sql = f"CREATE {table} SET " + ", ".join(set_parts)
                    try:
                        db.query(sql, params)
                        count += 1
                    except Exception as e:
                        print(f"    ERR on {table} CREATE: {e}")

            if (i + batch_size) % 500 == 0:
                print(f"    {table}: {count}/{len(rows)}...")

        total += count
        print(f"  {table}: {count} records imported")

    for edge in EDGE_TABLES:
        json_path = os.path.join(EXPORT_DIR, f"edge_{edge}.json")
        if not os.path.exists(json_path):
            continue
        with open(json_path) as f:
            rows = json.load(f)
        count = 0
        for row in rows:
            in_ref = row.get("in")
            out_ref = row.get("out")
            if not in_ref or not out_ref:
                continue

            from_id = (
                RecordID(in_ref["table"], in_ref["id"])
                if isinstance(in_ref, dict) and in_ref.get("_recordid")
                else in_ref
            )
            to_id = (
                RecordID(out_ref["table"], out_ref["id"])
                if isinstance(out_ref, dict) and out_ref.get("_recordid")
                else out_ref
            )

            extra = {k: v for k, v in row.items() if k not in ("id", "in", "out")}
            set_clause = ""
            params = {"from": from_id, "to": to_id}
            if extra:
                set_parts = []
                for k, v in extra.items():
                    if isinstance(v, dict) and v.get("_datetime"):
                        v = v["value"]
                    pname = f"p_{k}"
                    params[pname] = v
                    set_parts.append(f"{k} = ${pname}")
                set_clause = " SET " + ", ".join(set_parts)

            try:
                db.query(f"RELATE $from->{edge}->$to{set_clause}", params)
                count += 1
            except Exception as e:
                print(f"    ERR edge {edge}: {e}")

        if count:
            total += count
            print(f"  edge:{edge}: {count} edges imported")

    print(f"\n[IMPORT] Done. {total} total records imported into v3")

    for table in TABLES:
        r = db.query(f"SELECT count() FROM {table} GROUP ALL")
        c = r[0].get("count", 0) if r else 0
        print(f"  {table}: {c}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("export", "import"):
        print("Usage: python3 migrate_v2_to_v3.py [export|import]")
        sys.exit(1)

    if sys.argv[1] == "export":
        export_v2()
    else:
        import_v3()
