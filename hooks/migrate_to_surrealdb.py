#!/usr/bin/env python3
"""Migrate LanceDB + SQLite data to SurrealDB embedded (surrealkv://).

Usage:
    python3 hooks/migrate_to_surrealdb.py               # migrate only
    python3 hooks/migrate_to_surrealdb.py --verify       # verify counts after migration
    python3 hooks/migrate_to_surrealdb.py --validate     # quality validation (top-5 overlap)
    python3 hooks/migrate_to_surrealdb.py --verify --validate  # both
"""

import argparse
import os
import random
import sqlite3
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import lancedb
from surrealdb import Surreal

from shared.surreal_collection import TABLE_SCHEMAS, init_surreal_db

LANCE_DIR = os.path.expanduser("~/data/memory/lancedb/")
SURREAL_DIR = os.path.expanduser("~/data/memory/surrealdb/")
CLUSTERS_DB = os.path.expanduser("~/data/memory/clusters.db")
KG_DB = os.path.expanduser("~/data/memory/knowledge_graph.db")
BATCH_SIZE = 50
EMBEDDING_DIM = 4096


def migrate_lance_table(lance_db, surreal_coll, table_name):
    try:
        lt = lance_db.open_table(table_name)
    except Exception as e:
        print(f"  SKIP {table_name}: {e}")
        return 0

    rows = lt.to_pandas()
    total = len(rows)
    if total == 0:
        print(f"  {table_name}: 0 rows (empty)")
        return 0

    migrated = 0
    schema_fields = TABLE_SCHEMAS.get(table_name, {})
    meta_cols = set(schema_fields.keys()) - {"id", "text", "vector"}

    for start in range(0, total, BATCH_SIZE):
        batch = rows.iloc[start : start + BATCH_SIZE]
        ids = []
        documents = []
        vectors = []
        metadatas = []

        for _, row in batch.iterrows():
            doc_id = str(row.get("id", ""))
            text = str(row.get("text", "")) if row.get("text") is not None else ""
            vec = row.get("vector")
            if vec is not None:
                vec = [float(x) for x in vec]
                if len(vec) != EMBEDDING_DIM:
                    vec = vec[:EMBEDDING_DIM] + [0.0] * max(0, EMBEDDING_DIM - len(vec))
            else:
                vec = [0.0] * EMBEDDING_DIM

            meta = {}
            for col in meta_cols:
                val = row.get(col)
                if val is not None and str(val) != "nan":
                    field_type = schema_fields.get(col, "string")
                    if field_type == "float":
                        try:
                            meta[col] = float(val)
                        except (ValueError, TypeError):
                            meta[col] = 0.0
                    elif field_type == "int":
                        try:
                            meta[col] = int(val)
                        except (ValueError, TypeError):
                            meta[col] = 0
                    else:
                        meta[col] = str(val)

            ids.append(doc_id)
            documents.append(text)
            vectors.append(vec)
            metadatas.append(meta)

        surreal_coll.upsert(
            ids=ids, documents=documents, vectors=vectors, metadatas=metadatas
        )
        migrated += len(ids)

        if migrated % 500 == 0 or migrated == total:
            print(f"  {table_name}: {migrated}/{total}")

    return migrated


def migrate_clusters(surreal_db):
    if not os.path.exists(CLUSTERS_DB):
        print("  SKIP clusters: clusters.db not found")
        return 0

    conn = sqlite3.connect(CLUSTERS_DB)
    rows = conn.execute(
        "SELECT cluster_id, centroid, member_count, label, created_at, updated_at FROM clusters"
    ).fetchall()
    conn.close()

    migrated = 0
    for cluster_id, centroid_blob, member_count, label, created_at, updated_at in rows:
        if centroid_blob:
            n_floats = len(centroid_blob) // 4
            centroid = list(struct.unpack(f"{n_floats}f", centroid_blob))
            if len(centroid) != EMBEDDING_DIM:
                centroid = centroid[:EMBEDDING_DIM] + [0.0] * max(
                    0, EMBEDDING_DIM - len(centroid)
                )
        else:
            centroid = [0.0] * EMBEDDING_DIM

        safe_id = str(cluster_id).replace("'", "")
        surreal_db.query(
            f"UPSERT clusters:`{safe_id}` SET "
            "centroid = $c, member_count = $mc, label = $l, "
            "created_at = $ca, updated_at = $ua",
            {
                "c": centroid,
                "mc": member_count or 0,
                "l": label or "",
                "ca": created_at or "",
                "ua": updated_at or "",
            },
        )
        migrated += 1
        if migrated % 500 == 0:
            print(f"  clusters: {migrated}/{len(rows)}")

    print(f"  clusters: {migrated}/{len(rows)}")
    return migrated


def migrate_kg_edges(surreal_db):
    if not os.path.exists(KG_DB):
        print("  SKIP knowledge_graph: not found")
        return 0

    conn = sqlite3.connect(KG_DB)
    edges = conn.execute(
        "SELECT from_id, to_id, relation_type, strength FROM edges"
    ).fetchall()
    conn.close()

    migrated = 0
    for from_id, to_id, relation_type, strength in edges:
        safe_src = str(from_id).replace("'", "")
        safe_tgt = str(to_id).replace("'", "")
        safe_rel = str(relation_type).replace("'", "").replace(" ", "_").lower()
        try:
            surreal_db.query(
                f"RELATE knowledge:`{safe_src}`->{safe_rel}->knowledge:`{safe_tgt}` "
                "SET strength = $w, migrated = true",
                {"w": strength or 0.0},
            )
            migrated += 1
        except Exception:
            pass

    print(f"  kg_edges: {migrated}/{len(edges)}")
    return migrated


def verify_counts(lance_db, surreal_colls):
    print("\n--- VERIFICATION ---")
    all_ok = True
    for table_name in [
        "knowledge",
        "fix_outcomes",
        "observations",
        "web_pages",
        "quarantine",
    ]:
        try:
            lt = lance_db.open_table(table_name)
            lance_count = lt.count_rows()
        except Exception:
            lance_count = 0
        surreal_count = surreal_colls[table_name].count()
        match = "OK" if surreal_count == lance_count else "MISMATCH"
        if match != "OK":
            all_ok = False
        print(f"  {table_name}: lance={lance_count}, surreal={surreal_count} [{match}]")

    surreal_cluster_count = surreal_colls["clusters"].count()
    if os.path.exists(CLUSTERS_DB):
        conn = sqlite3.connect(CLUSTERS_DB)
        sqlite_count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        conn.close()
    else:
        sqlite_count = 0
    match = "OK" if surreal_cluster_count == sqlite_count else "MISMATCH"
    if match != "OK":
        all_ok = False
    print(
        f"  clusters: sqlite={sqlite_count}, surreal={surreal_cluster_count} [{match}]"
    )

    return all_ok


def validate_quality(lance_db, surreal_colls, n_queries=20):
    print("\n--- QUALITY VALIDATION ---")
    try:
        lt = lance_db.open_table("knowledge")
        df = lt.to_pandas()
    except Exception as e:
        print(f"  SKIP: cannot read knowledge table: {e}")
        return

    if len(df) < n_queries:
        n_queries = len(df)

    sample_indices = random.sample(range(len(df)), n_queries)
    overlaps = []

    for idx in sample_indices:
        row = df.iloc[idx]
        query_vec = [float(x) for x in row["vector"]]
        query_id = str(row["id"])

        lance_results = (
            lt.search(query_vec, vector_column_name="vector")
            .distance_type("cosine")
            .limit(5)
            .to_list()
        )
        lance_ids = set(r["id"] for r in lance_results)

        surreal_result = surreal_colls["knowledge"].query(
            query_vector=query_vec, n_results=5, include=["distances"]
        )
        surreal_ids = set(surreal_result["ids"][0])

        overlap = len(lance_ids & surreal_ids) / max(len(lance_ids), 1)
        overlaps.append(overlap)

    avg_overlap = sum(overlaps) / len(overlaps)
    min_overlap = min(overlaps)
    print(f"  Queries: {n_queries}")
    print(f"  Average top-5 overlap: {avg_overlap:.1%}")
    print(f"  Min overlap: {min_overlap:.1%}")
    print(f"  Target: >= 80%")
    print(f"  Result: {'PASS' if avg_overlap >= 0.8 else 'FAIL'}")
    return avg_overlap >= 0.8


def main():
    parser = argparse.ArgumentParser(description="Migrate LanceDB to SurrealDB")
    parser.add_argument(
        "--verify", action="store_true", help="Verify counts after migration"
    )
    parser.add_argument("--validate", action="store_true", help="Quality validation")
    parser.add_argument(
        "--skip-migrate",
        action="store_true",
        help="Skip migration, only verify/validate",
    )
    args = parser.parse_args()

    lance_db = lancedb.connect(LANCE_DIR)
    surreal_db = Surreal(f"surrealkv://{SURREAL_DIR}")
    surreal_db.use("memory", "main")

    print("Initializing SurrealDB tables...")
    collections = init_surreal_db(surreal_db, embedding_dim=EMBEDDING_DIM)

    if not args.skip_migrate:
        print("\n=== MIGRATING DATA ===")
        t0 = time.time()

        total = 0
        for table_name in [
            "knowledge",
            "fix_outcomes",
            "observations",
            "web_pages",
            "quarantine",
        ]:
            n = migrate_lance_table(lance_db, collections[table_name], table_name)
            total += n

        print("\nMigrating clusters...")
        total += migrate_clusters(surreal_db)

        print("\nMigrating knowledge graph edges...")
        migrate_kg_edges(surreal_db)

        elapsed = time.time() - t0
        print(f"\n=== MIGRATION COMPLETE: {total} records in {elapsed:.1f}s ===")

    if args.verify:
        ok = verify_counts(lance_db, collections)
        if not ok:
            print("\nWARNING: Count mismatches detected!")
            sys.exit(1)

    if args.validate:
        ok = validate_quality(lance_db, collections)
        if not ok:
            print("\nWARNING: Quality below threshold!")
            sys.exit(1)

    surreal_db.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
