#!/usr/bin/env python3
"""Search indexed web pages via LanceDB semantic search."""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from shared import memory_socket


def search_pages(query: str, n_results: int = 5) -> list[dict]:
    """Semantic search against web_pages collection."""
    try:
        result = memory_socket.query(
            "web_pages",
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
    except memory_socket.WorkerUnavailable:
        print("Error: Memory worker not available. Is memory_server running?", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if "Unknown collection" in str(e):
            return []
        raise

    if not result or not result.get("ids") or not result["ids"][0]:
        return []

    hits = []
    ids = result["ids"][0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]

    for i, doc_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        doc = docs[i] if i < len(docs) else ""
        dist = dists[i] if i < len(dists) else 1.0

        # Cosine distance to similarity score
        similarity = round(1.0 - dist, 3)

        hits.append({
            "id": doc_id,
            "url": meta.get("url", "unknown"),
            "title": meta.get("title", "Untitled"),
            "chunk_index": meta.get("chunk_index", 0),
            "total_chunks": meta.get("total_chunks", 1),
            "similarity": similarity,
            "preview": doc[:200] + "..." if len(doc) > 200 else doc,
            "full_content": doc,
        })

    return hits


def main():
    parser = argparse.ArgumentParser(description="Search indexed web pages")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--n", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--full", action="store_true", help="Show full content instead of preview")
    args = parser.parse_args()

    hits = search_pages(args.query, n_results=args.n)

    if not hits:
        print(f"No results for: {args.query}")
        print("(Have you indexed any pages? Try: /web index <url>)")
        return

    print(f"Found {len(hits)} results for: {args.query}\n")

    for i, hit in enumerate(hits, 1):
        print(f"  [{i}] {hit['title']}")
        print(f"      URL: {hit['url']} (chunk {hit['chunk_index']+1}/{hit['total_chunks']})")
        print(f"      Score: {hit['similarity']}")
        if args.full:
            print(f"      Content:\n{hit['full_content']}")
        else:
            print(f"      Preview: {hit['preview']}")
        print()


if __name__ == "__main__":
    main()
