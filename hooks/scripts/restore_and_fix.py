"""Restore knowledge from backup, backfill cluster_id, fix zero vectors.

Single table write — no row-by-row updates, no fragmentation.
Server must be STOPPED.

Usage: python3 restore_and_fix.py [--dry-run]
"""

import sys
import os
import json
import time
import numpy as np
import lancedb
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.cluster_store import ClusterStore

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
BACKUP_DIR = os.path.join(MEMORY_DIR, "lancedb.backup")
CLUSTERS_DB = os.path.join(MEMORY_DIR, "clusters.db")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "config.json")

NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
MODEL = "nvidia/nv-embed-v1"


def get_api_key():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            key = json.load(f).get("nim_api_key", "")
            if key:
                return key
    return os.environ.get("NIM_API_KEY", "")


def embed_texts(texts, api_key):
    safe = [t if t and t.strip() else "[empty]" for t in texts]
    resp = requests.post(
        NIM_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "input": safe,
            "input_type": "passage",
            "encoding_format": "float",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return [d["embedding"] for d in resp.json()["data"]]


def run(dry_run=False):
    t0 = time.time()

    # 1. Read backup
    bak_db = lancedb.connect(BACKUP_DIR)
    bak_tbl = bak_db.open_table("knowledge")
    schema = bak_tbl.schema
    df = bak_tbl.to_pandas()
    sys.stderr.write(f"Loaded {len(df)} rows from backup\n")

    # 2. Fix string columns — replace NaN with empty string
    string_cols = [f.name for f in schema if "string" in str(f.type)]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    sys.stderr.write(f"Cleaned NaN in {len(string_cols)} string columns\n")

    # 3. Fix zero vectors via NIM API
    zero_mask = df["vector"].apply(
        lambda v: np.count_nonzero(np.array(v, dtype=np.float32)) == 0
    )
    zero_count = zero_mask.sum()
    sys.stderr.write(f"Zero-vector rows: {zero_count}\n")

    if zero_count > 0:
        api_key = get_api_key()
        if not api_key:
            sys.stderr.write("WARNING: No NIM API key, skipping zero-vector fix\n")
        else:
            zero_indices = df.index[zero_mask].tolist()
            texts = [str(df.loc[i, "text"]) for i in zero_indices]
            sys.stderr.write(f"Embedding {len(texts)} texts via NIM...\n")
            all_vecs = []
            for i in range(0, len(texts), 10):
                batch = texts[i : i + 10]
                vecs = embed_texts(batch, api_key)
                all_vecs.extend(vecs)
                sys.stderr.write(f"  Embedded {min(i + 10, len(texts))}/{len(texts)}\n")

            fixed_vecs = 0
            for idx, vec in zip(zero_indices, all_vecs):
                if np.count_nonzero(vec) > 0:
                    df.at[idx, "vector"] = vec
                    fixed_vecs += 1
            sys.stderr.write(f"Fixed {fixed_vecs}/{zero_count} vectors\n")

    # 4. Backfill cluster_id
    cs = ClusterStore(CLUSTERS_DB)
    missing_mask = df["cluster_id"].isna() | (df["cluster_id"] == "")
    missing_count = missing_mask.sum()
    sys.stderr.write(f"Missing cluster_id: {missing_count}\n")

    assigned = 0
    for idx in df.index[missing_mask]:
        vec = df.loc[idx, "vector"]
        if vec is None:
            continue
        vec_arr = np.array(vec, dtype=np.float32)
        if vec_arr.shape[0] != 4096 or np.count_nonzero(vec_arr) == 0:
            continue
        cid = cs.assign(vec_arr.tolist(), str(df.loc[idx, "text"]))
        if cid:
            df.at[idx, "cluster_id"] = str(cid)
            assigned += 1
        if assigned % 500 == 0 and assigned > 0:
            sys.stderr.write(f"  Assigned {assigned}...\n")

    sys.stderr.write(f"Assigned {assigned}/{missing_count} cluster_ids\n")

    if dry_run:
        sys.stderr.write("DRY RUN — no write.\n")
        return

    # 5. Convert vectors from ndarray to list for PyArrow
    df["vector"] = df["vector"].apply(
        lambda v: v.tolist() if isinstance(v, np.ndarray) else list(v)
    )

    # 6. Drop empty table and rewrite
    sys.stderr.write("Writing new knowledge table...\n")
    db = lancedb.connect(LANCE_DIR)
    db.drop_table("knowledge")
    db.create_table("knowledge", data=df, schema=schema)

    # 7. Verify
    new_tbl = db.open_table("knowledge")
    final_count = new_tbl.count_rows()
    sys.stderr.write(f"Verified: {final_count} rows written\n")
    sys.stderr.write(f"Total time: {time.time() - t0:.1f}s\n")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
