#!/usr/bin/env python3
"""Trim oversized knowledge memory entries using Claude Sonnet API.

Finds all entries in the knowledge table with text > THRESHOLD chars,
condenses each to ≤800 chars via Sonnet API, re-embeds with
nomic-embed-text-v2-moe, and writes back to LanceDB.

Usage:
    python3 trim_memories.py              # dry-run: show before/after, no writes
    python3 trim_memories.py --write      # condense + write (with confirmation)
    python3 trim_memories.py --write --yes  # skip confirmation prompt
    python3 trim_memories.py --limit 10   # process at most 10 entries
    python3 trim_memories.py --threshold 1000  # custom trim threshold (default 2000)

Note: The memory MCP server may be running concurrently. LanceDB uses MVCC
so reads are safe, but prefer running this during low-activity periods.
"""

import os
import sys
import time
import argparse

LANCE_DIR = os.path.join(os.path.expanduser("~"), "data", "memory", "lancedb")
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v2-moe"
EMBEDDING_DIM = 768
TRIM_THRESHOLD = 2000  # entries longer than this will be condensed
TARGET_MAX = 800  # target max chars after condensing
PREVIEW_LEN = 120  # preview field length

CONDENSE_PROMPT = (
    "You are condensing a technical memory entry for an AI coding assistant.\n"
    "Rules:\n"
    "- Preserve ALL key facts, decisions, file paths, error messages, outcomes, IDs.\n"
    "- Drop filler words, repetition, and verbose phrasing.\n"
    "- Keep structured lists/bullets if present — just shorten each item.\n"
    "- Output ONLY the condensed text. No preamble, no explanation.\n"
    "- Hard limit: {max_chars} characters.\n\n"
    "Text to condense:\n{text}"
)


# ── LanceDB helpers ──────────────────────────────────────────────────────────


def open_table():
    import lancedb

    db = lancedb.connect(LANCE_DIR)
    return db, db.open_table("knowledge")


def scan_all(tbl):
    """Return all rows from the knowledge table as a list of dicts."""
    return tbl.search().limit(200000).to_list()


# ── Embedding ────────────────────────────────────────────────────────────────


def load_embed_model():
    print("Loading embedding model (nomic-embed-text-v2-moe)...")
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
    print("  Model loaded.")
    return model


def embed_batch(model, texts):
    """Return list of 768-dim float lists."""
    vecs = model.encode(texts, show_progress_bar=False, batch_size=32)
    return [v.tolist() for v in vecs]


# ── Claude condensing ────────────────────────────────────────────────────────


def make_client():
    import anthropic

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=key)


def condense(client, text, max_chars=TARGET_MAX):
    prompt = CONDENSE_PROMPT.format(max_chars=max_chars, text=text)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    result = msg.content[0].text.strip()
    # Hard cap in case the model went slightly over
    if len(result) > max_chars:
        # Trim at word boundary
        result = result[:max_chars].rsplit(" ", 1)[0]
    return result


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--write", action="store_true", help="Commit condensed entries to LanceDB"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt (requires --write)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Process at most N entries (0 = all)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=TRIM_THRESHOLD,
        help=f"Trim entries longer than N chars (default {TRIM_THRESHOLD})",
    )
    args = parser.parse_args()

    # ── Connect & scan ───────────────────────────────────────────────────────
    print(f"Connecting to LanceDB: {LANCE_DIR}")
    db, tbl = open_table()

    print("Scanning knowledge table...")
    all_rows = scan_all(tbl)
    print(f"  Total entries : {len(all_rows)}")

    oversized = [r for r in all_rows if len(r.get("text", "")) > args.threshold]
    print(f"  Over {args.threshold} chars: {len(oversized)}")

    if not oversized:
        print("Nothing to trim.")
        return 0

    if args.limit > 0:
        oversized = oversized[: args.limit]
        print(f"  Capped at     : {len(oversized)} (--limit {args.limit})")

    mode_label = "[DRY-RUN]" if not args.write else "[WRITE]"
    print(f"\n{mode_label} Processing {len(oversized)} entries...\n")
    print("=" * 72)

    # ── Condense with Claude ─────────────────────────────────────────────────
    client = make_client()

    condensed_entries = []  # list of (id, new_text, original_row)
    errors = []

    for i, row in enumerate(oversized, 1):
        row_id = row["id"]
        original = row.get("text", "")
        orig_len = len(original)
        tags = row.get("tags", "")[:60]

        print(f"[{i:>3}/{len(oversized)}] {row_id[:20]}  {orig_len} chars")
        print(f"  tags   : {tags}")
        print(f"  before : {original[:120]!r}")

        try:
            new_text = condense(client, original)
            new_len = len(new_text)
            saved = orig_len - new_len
            print(f"  after  : {new_text[:120]!r}")
            print(f"  result : {orig_len} → {new_len} chars  (saved {saved})")
            condensed_entries.append((row_id, new_text, row))
        except Exception as e:
            print(f"  ERROR  : {e}")
            errors.append((row_id, str(e)))

        print()

        # Respect rate limits (~1 req/sec comfortable margin)
        if i < len(oversized):
            time.sleep(1.1)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 72)
    total_before = sum(len(r.get("text", "")) for _, _, r in condensed_entries)
    total_after = sum(len(t) for _, t, _ in condensed_entries)
    print(f"Condensed : {len(condensed_entries)}  |  Errors: {len(errors)}")
    if condensed_entries:
        print(
            f"Chars     : {total_before:,} → {total_after:,}  "
            f"(saved {total_before - total_after:,}, "
            f"{100 * (total_before - total_after) / total_before:.0f}%)"
        )

    if errors:
        print(f"\nFailed entries:")
        for eid, emsg in errors:
            print(f"  {eid[:20]}: {emsg}")

    if not condensed_entries:
        print("Nothing to write.")
        return 1

    if not args.write:
        print(
            f"\n[DRY-RUN] Re-run with --write to commit {len(condensed_entries)} changes."
        )
        return 0

    # ── Confirmation ─────────────────────────────────────────────────────────
    if not args.yes:
        resp = input(
            f"\nWrite {len(condensed_entries)} updated entries to LanceDB? [y/N] "
        )
        if resp.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 0

    # ── Re-embed ─────────────────────────────────────────────────────────────
    embed_model = load_embed_model()
    new_texts = [t for _, t, _ in condensed_entries]
    print(f"Embedding {len(new_texts)} entries...")
    vectors = embed_batch(embed_model, new_texts)
    print("  Done.")

    # ── Build records ─────────────────────────────────────────────────────────
    schema_names = tbl.schema.names  # column names from live table

    records = []
    for (row_id, new_text, orig_row), vector in zip(condensed_entries, vectors):
        record = {}
        for col in schema_names:
            if col == "id":
                record["id"] = row_id
            elif col == "text":
                record["text"] = new_text
            elif col == "vector":
                record["vector"] = vector
            elif col == "preview":
                record["preview"] = new_text[:PREVIEW_LEN]
            else:
                val = orig_row.get(col)
                if val is None:
                    # Pick a safe default based on type
                    import pyarrow as pa

                    ftype = tbl.schema.field(col).type
                    if pa.types.is_floating(ftype):
                        val = 0.0
                    elif pa.types.is_integer(ftype):
                        val = 0
                    else:
                        val = ""
                # Coerce any list/dict metadata to string
                if isinstance(val, (list, dict)) and col != "vector":
                    val = str(val)
                record[col] = val
        records.append(record)

    # ── Write ────────────────────────────────────────────────────────────────
    print(f"Writing {len(records)} records to LanceDB...")
    try:
        (tbl.merge_insert("id").when_matched_update_all().execute(records))
        print(f"  Done. {len(records)} entries updated.")
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1

    print("\nTrim complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
