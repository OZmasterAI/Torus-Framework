#!/usr/bin/env python3
"""Import condensed memory texts back into LanceDB.

Reads a JSONL file of {id, new_text} pairs, re-embeds each with
nomic-embed-text-v2-moe, and updates the knowledge table via merge_insert.

Usage:
    python3 import_condensed_memories.py condensed.jsonl        # dry-run
    python3 import_condensed_memories.py condensed.jsonl --write
    python3 import_condensed_memories.py condensed.jsonl --write --yes
"""

import json
import os
import sys
import argparse

LANCE_DIR = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v2-moe"
EMBEDDING_DIM = 768
PREVIEW_LEN = 120


def load_embed_model():
    print("Loading embedding model...", file=sys.stderr)
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
    print("  Done.", file=sys.stderr)
    return model


def embed_batch(model, texts, batch_size=32):
    vecs = model.encode(texts, show_progress_bar=True, batch_size=batch_size)
    return [v.tolist() for v in vecs]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("input", help="JSONL file with {id, new_text} pairs")
    parser.add_argument("--write", action="store_true", help="Commit to LanceDB")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    args = parser.parse_args()

    # Load condensed entries
    entries = []
    with open(args.input) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "id" not in obj or "new_text" not in obj:
                    print(
                        f"Line {i}: missing id or new_text — skipping", file=sys.stderr
                    )
                    continue
                if len(obj["new_text"]) > 800:
                    print(
                        f"Line {i} ({obj['id'][:16]}): new_text is {len(obj['new_text'])} chars — truncating to 800",
                        file=sys.stderr,
                    )
                    obj["new_text"] = obj["new_text"][:800].rsplit(" ", 1)[0]
                entries.append(obj)
            except json.JSONDecodeError as e:
                print(f"Line {i}: JSON error — {e}", file=sys.stderr)

    print(f"Loaded {len(entries)} condensed entries from {args.input}")

    if not entries:
        print("Nothing to import.")
        return 1

    # Validate lengths
    ok = sum(1 for e in entries if len(e["new_text"]) <= 800)
    print(f"Within 800 chars: {ok}/{len(entries)}")

    if not args.write:
        print("\n[DRY-RUN] Showing first 3 entries:")
        for e in entries[:3]:
            print(
                f"  {e['id'][:20]}  {len(e['new_text'])} chars: {e['new_text'][:100]!r}"
            )
        print(f"\nRe-run with --write to commit {len(entries)} changes.")
        return 0

    if not args.yes:
        resp = input(f"\nWrite {len(entries)} entries to LanceDB? [y/N] ")
        if resp.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 0

    # Connect to LanceDB and fetch originals
    import lancedb

    db = lancedb.connect(LANCE_DIR)
    tbl = db.open_table("knowledge")

    ids = [e["id"] for e in entries]
    id_to_new_text = {e["id"]: e["new_text"] for e in entries}

    print(f"Fetching {len(ids)} originals from LanceDB...")
    escaped = ", ".join(f"'{i}'" for i in ids)
    orig_rows = (
        tbl.search()
        .where(f"id IN ({escaped})", prefilter=True)
        .limit(len(ids) + 10)
        .to_list()
    )
    orig_map = {r["id"]: r for r in orig_rows}
    found = sum(1 for i in ids if i in orig_map)
    missing = [i for i in ids if i not in orig_map]
    print(f"  Found: {found}  Missing: {len(missing)}")
    if missing:
        print(f"  Missing IDs (skipping): {missing[:5]}")
        entries = [e for e in entries if e["id"] in orig_map]

    # Re-embed
    embed_model = load_embed_model()
    texts = [id_to_new_text[e["id"]] for e in entries]
    print(f"Embedding {len(texts)} texts...")
    vectors = embed_batch(embed_model, texts)
    print(f"  Done.")

    # Build records (preserve all original metadata)
    schema_names = tbl.schema.names
    records = []
    for entry, vector in zip(entries, vectors):
        eid = entry["id"]
        new_text = id_to_new_text[eid]
        orig = orig_map[eid]
        record = {}
        for col in schema_names:
            if col == "id":
                record["id"] = eid
            elif col == "text":
                record["text"] = new_text
            elif col == "vector":
                record["vector"] = vector
            elif col == "preview":
                record["preview"] = new_text[:PREVIEW_LEN]
            else:
                val = orig.get(col)
                if val is None:
                    import pyarrow as pa

                    ftype = tbl.schema.field(col).type
                    if pa.types.is_floating(ftype):
                        val = 0.0
                    elif pa.types.is_integer(ftype):
                        val = 0
                    else:
                        val = ""
                if isinstance(val, (list, dict)) and col != "vector":
                    val = str(val)
                record[col] = val
        records.append(record)

    # Write
    print(f"Writing {len(records)} records to LanceDB...")
    try:
        (tbl.merge_insert("id").when_matched_update_all().execute(records))
        print(f"  Done. {len(records)} entries updated.")
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    print("\nImport complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
