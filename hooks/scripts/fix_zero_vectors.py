"""Re-embed knowledge rows with zero vectors, then assign clusters.

Calls NVIDIA NIM API directly for embeddings, updates LanceDB in-place.
Memory server must be STOPPED (LanceDB writer lock).

Usage: python3 fix_zero_vectors.py [--dry-run]
"""

import sys
import os
import json
import numpy as np
import lancedb
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.cluster_store import ClusterStore

MEMORY_DIR = os.path.join(os.path.expanduser("~"), "data", "memory")
LANCE_DIR = os.path.join(MEMORY_DIR, "lancedb")
CLUSTERS_DB = os.path.join(MEMORY_DIR, "clusters.db")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "config.json")

NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
MODEL = "nvidia/nv-embed-v1"
DIM = 4096


def get_api_key():
    for path in [CONFIG_PATH, os.path.expanduser("~/.claude/hooks/config.json")]:
        if os.path.exists(path):
            with open(path) as f:
                cfg = json.load(f)
                key = cfg.get("nim_api_key", "")
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
    cs = ClusterStore(CLUSTERS_DB)

    df = tbl.to_pandas()
    zero_mask = df["vector"].apply(
        lambda v: np.count_nonzero(np.array(v, dtype=np.float32)) == 0
    )
    zeros = df[zero_mask]
    sys.stderr.write(f"Found {len(zeros)} rows with zero vectors\n")

    if len(zeros) == 0:
        return

    api_key = get_api_key()
    if not api_key:
        sys.stderr.write("ERROR: No NIM API key found\n")
        return

    texts = [str(row.get("text", "")) for _, row in zeros.iterrows()]
    ids = [row["id"] for _, row in zeros.iterrows()]

    sys.stderr.write(f"Embedding {len(texts)} texts via NIM API...\n")
    # Batch in groups of 10 (API limit)
    all_vecs = []
    for i in range(0, len(texts), 10):
        batch = texts[i : i + 10]
        vecs = embed_texts(batch, api_key)
        all_vecs.extend(vecs)
        sys.stderr.write(f"  Embedded {min(i + 10, len(texts))}/{len(texts)}\n")

    success = sum(1 for v in all_vecs if np.count_nonzero(v) > 0)
    sys.stderr.write(f"Got {success}/{len(all_vecs)} non-zero embeddings\n")

    if dry_run:
        sys.stderr.write("DRY RUN — no writes.\n")
        return

    written = 0
    errors = 0
    for doc_id, vec, text in zip(ids, all_vecs, texts):
        if np.count_nonzero(vec) == 0:
            errors += 1
            continue
        try:
            safe_id = doc_id.replace("'", "''")
            tbl.update(where=f"id = '{safe_id}'", values={"vector": vec})
            cid = cs.assign(vec, text)
            if cid:
                tbl.update(where=f"id = '{safe_id}'", values={"cluster_id": cid})
            written += 1
        except Exception as e:
            errors += 1
            sys.stderr.write(f"  Error on {doc_id}: {e}\n")

    sys.stderr.write(f"Done: {written} fixed, {errors} errors\n")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
