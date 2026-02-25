#!/usr/bin/env python3
"""List all indexed web pages with metadata."""

import argparse
import fnmatch
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from shared import chromadb_socket


def list_pages(pattern: str = None) -> list[dict]:
    """List indexed URLs, grouped by URL. Optional glob pattern filter."""
    try:
        result = chromadb_socket.get("web_pages", limit=500, include=["metadatas"])
    except chromadb_socket.WorkerUnavailable:
        print("Error: Memory worker not available. Is memory_server running?", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if "Unknown collection" in str(e):
            return []
        raise

    if not result or not result.get("metadatas"):
        return []

    # Group by URL
    url_groups = defaultdict(lambda: {"chunks": 0, "title": "", "indexed_at": "", "hash": ""})

    for meta in result["metadatas"]:
        url = meta.get("url", "unknown")

        if pattern and not fnmatch.fnmatch(url, f"*{pattern}*"):
            continue

        group = url_groups[url]
        group["chunks"] += 1
        if not group["title"]:
            group["title"] = meta.get("title", "Untitled")
        if not group["indexed_at"]:
            group["indexed_at"] = meta.get("indexed_at", "unknown")
        if not group["hash"]:
            group["hash"] = meta.get("content_hash", "")

    pages = []
    for url, info in sorted(url_groups.items()):
        pages.append({
            "url": url,
            "title": info["title"],
            "chunks": info["chunks"],
            "indexed_at": info["indexed_at"],
            "content_hash": info["hash"],
        })

    return pages


def main():
    parser = argparse.ArgumentParser(description="List indexed web pages")
    parser.add_argument("--pattern", help="URL pattern to filter (glob-style)")
    args = parser.parse_args()

    pages = list_pages(pattern=args.pattern)

    if not pages:
        if args.pattern:
            print(f"No indexed pages matching: {args.pattern}")
        else:
            print("No indexed pages. Try: /web index <url>")
        return

    total_chunks = sum(p["chunks"] for p in pages)
    print(f"Indexed pages: {len(pages)} URLs, {total_chunks} total chunks\n")

    for p in pages:
        print(f"  {p['title']}")
        print(f"    URL: {p['url']}")
        print(f"    Chunks: {p['chunks']} | Indexed: {p['indexed_at']} | Hash: {p['content_hash']}")
        print()


if __name__ == "__main__":
    main()
