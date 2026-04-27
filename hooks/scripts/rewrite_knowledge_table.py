"""Rewrite knowledge table: fix zero vectors + compact all fragments.

Reads entire table into pandas, re-embeds zero-vector rows via NIM API,
assigns clusters, then overwrites the table in one shot.

Server must be STOPPED.

Usage: python3 rewrite_knowledge_table.py [--dry-run]
"""

import sys
import os
import json
import numpy as np
import lancedb
import pyarrow as pa
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.cluster_store import ClusterStore

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
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
    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")
    schema = tbl.schema

    sys.stderr.write("Reading entire knowledge table...\n")
    df = tbl.to_pandas()
    sys.stderr.write(f"Loaded {len(df)} rows\n")

    zero_mask = df["vector"].apply(
        lambda v: np.count_nonzero(np.array(v, dtype=np.float32)) == 0
    )
    zero_count = zero_mask.sum()
    sys.stderr.write(f"Zero-vector rows: {zero_count}\n")

    if zero_count > 0:
        api_key = get_api_key()
        if not api_key:
            sys.stderr.write("ERROR: No NIM API key\n")
            return

        zero_indices = df.index[zero_mask].tolist()
        texts = [str(df.loc[i, "text"]) for i in zero_indices]

        sys.stderr.write(f"Embedding {len(texts)} texts via NIM...\n")
        all_vecs = []
        for batch_start in range(0, len(texts), 10):
            batch = texts[batch_start : batch_start + 10]
            vecs = embed_texts(batch, api_key)
            all_vecs.extend(vecs)
            sys.stderr.write(
                f"  Embedded {min(batch_start + 10, len(texts))}/{len(texts)}\n"
            )

        cs = ClusterStore(CLUSTERS_DB)
        fixed = 0
        for idx, vec, text in zip(zero_indices, all_vecs, texts):
            if np.count_nonzero(vec) > 0:
                df.at[idx, "vector"] = vec
                cid = cs.assign(vec, text)
                if cid:
                    df.at[idx, "cluster_id"] = cid
                fixed += 1
        sys.stderr.write(f"Fixed {fixed}/{zero_count} vectors\n")

    if dry_run:
        sys.stderr.write("DRY RUN — no write.\n")
        return

    sys.stderr.write("Dropping and rewriting knowledge table...\n")
    db.drop_table("knowledge")

    records = df.to_dict("records")
    for r in records:
        if isinstance(r.get("vector"), np.ndarray):
            r["vector"] = r["vector"].tolist()

    db.create_table("knowledge", data=records, schema=schema)
    sys.stderr.write(f"Done — rewrote {len(records)} rows in one shot.\n")

    new_tbl = db.open_table("knowledge")
    sys.stderr.write(f"Verified: {new_tbl.count_rows()} rows\n")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
