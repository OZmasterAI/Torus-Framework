#!/usr/bin/env python3
"""Delete indexed web pages by URL pattern."""

import argparse
import fnmatch
import sys
import os

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from shared import chromadb_socket


def delete_pages(pattern: str) -> dict:
    """Delete pages matching URL pattern. Returns summary."""
    try:
        result = chromadb_socket.get("web_pages", limit=500, include=["metadatas"])
    except chromadb_socket.WorkerUnavailable:
        print("Error: Memory worker not available. Is memory_server running?", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if "Unknown collection" in str(e):
            return {"deleted": 0, "remaining": 0, "urls": []}
        raise

    if not result or not result.get("ids"):
        return {"deleted": 0, "remaining": 0, "urls": []}

    ids = result["ids"]
    metas = result.get("metadatas", [])

    matching_ids = []
    matching_urls = set()
    remaining = 0

    for i, doc_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        url = meta.get("url", "")

        if fnmatch.fnmatch(url, f"*{pattern}*"):
            matching_ids.append(doc_id)
            matching_urls.add(url)
        else:
            remaining += 1

    if matching_ids:
        chromadb_socket.delete("web_pages", matching_ids)

    return {
        "deleted": len(matching_ids),
        "remaining": remaining,
        "urls": sorted(matching_urls),
    }


def main():
    parser = argparse.ArgumentParser(description="Delete indexed web pages")
    parser.add_argument("pattern", help="URL pattern to match for deletion")
    args = parser.parse_args()

    result = delete_pages(args.pattern)

    if result["deleted"] == 0:
        print(f"No pages matching: {args.pattern}")
        return

    print(f"Deleted {result['deleted']} chunks from {len(result['urls'])} URLs:")
    for url in result["urls"]:
        print(f"  - {url}")
    print(f"\nRemaining chunks: {result['remaining']}")


if __name__ == "__main__":
    main()
