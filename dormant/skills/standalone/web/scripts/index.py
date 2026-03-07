#!/usr/bin/env python3
"""Web page indexer — fetch, clean, chunk, and upsert to LanceDB web_pages collection."""

import argparse
import hashlib
import re
import sys
import os
import time

# Add shared module path
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md


def fetch_html(url: str) -> tuple[str, str]:
    """Fetch URL and return (html_content, final_url)."""
    resp = httpx.get(url, follow_redirects=True, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ClaudeWebIndexer/1.0)"
    })
    resp.raise_for_status()
    return resp.text, str(resp.url)


def extract_content(html: str) -> tuple[str, str]:
    """Strip boilerplate and convert to markdown. Returns (markdown, title)."""
    soup = BeautifulSoup(html, "lxml")

    # Extract title before stripping
    title = soup.title.string.strip() if soup.title and soup.title.string else "Untitled"

    # Remove noise elements
    for tag in soup.find_all(["nav", "footer", "header", "script", "style",
                               "noscript", "iframe", "svg", "aside"]):
        tag.decompose()

    # Remove common ad/tracking divs
    for attr in ["id", "class"]:
        for el in soup.find_all(attrs={attr: re.compile(
            r"(sidebar|menu|cookie|banner|popup|modal|social|share|comment|ad[s]?[-_]|tracking)",
            re.I
        )}):
            el.decompose()

    # Find main content area (prefer article/main, fall back to body)
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if main is None:
        main = soup

    # Convert to markdown
    markdown = md(str(main), heading_style="ATX", strip=["img"])

    # Clean up excessive whitespace
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = markdown.strip()

    return markdown, title


def quality_check(content: str) -> tuple[bool, str, float]:
    """Validate content quality. Returns (passed, reason, score)."""
    words = content.split()
    word_count = len(words)

    if word_count < 50:
        return False, f"Too short: {word_count} words (minimum 50)", 0.0

    # Check link density (markdown links)
    link_chars = sum(len(m) for m in re.findall(r"\[.*?\]\(.*?\)", content))
    total_chars = len(content)
    link_ratio = link_chars / total_chars if total_chars > 0 else 0

    if link_ratio > 0.8:
        return False, f"Too many links: {link_ratio:.0%} link content", link_ratio

    # Quality score: penalize high link ratio, reward word count
    score = min(1.0, word_count / 500) * (1.0 - link_ratio * 0.5)
    return True, "OK", round(score, 2)


def content_hash(content: str) -> str:
    """SHA-256 hash of content for dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def chunk_content(content: str, max_words: int = 500) -> list[str]:
    """Split content into chunks by paragraphs, targeting ~max_words per chunk."""
    paragraphs = content.split("\n\n")
    chunks = []
    current = []
    current_words = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_words = len(para.split())

        # If single paragraph exceeds max, split by sentences
        if para_words > max_words and not current:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sent_buf = []
            sent_words = 0
            for sent in sentences:
                sw = len(sent.split())
                if sent_words + sw > max_words and sent_buf:
                    chunks.append(" ".join(sent_buf))
                    sent_buf = [sent]
                    sent_words = sw
                else:
                    sent_buf.append(sent)
                    sent_words += sw
            if sent_buf:
                chunks.append(" ".join(sent_buf))
            continue

        if current_words + para_words > max_words and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks if chunks else [content]


def index_url(url: str, preview: bool = False) -> dict:
    """Main indexing pipeline. Returns summary dict."""
    # Fetch
    html, final_url = fetch_html(url)

    # Extract
    markdown, title = extract_content(html)

    # Quality check
    passed, reason, score = quality_check(markdown)
    if not passed:
        return {"status": "rejected", "url": final_url, "title": title,
                "reason": reason, "score": score}

    # Check for duplicate
    c_hash = content_hash(markdown)

    # Chunk
    chunks = chunk_content(markdown)
    total_words = len(markdown.split())

    if preview:
        return {
            "status": "preview",
            "url": final_url,
            "title": title,
            "chunks": len(chunks),
            "words": total_words,
            "quality_score": score,
            "content_hash": c_hash,
            "first_chunk_preview": chunks[0][:300] + "..." if len(chunks[0]) > 300 else chunks[0],
        }

    # Upsert to LanceDB
    from shared import memory_socket

    # Check for existing content with same hash (dedup)
    try:
        existing = memory_socket.get("web_pages", limit=100, include=["metadatas"])
        if existing and existing.get("metadatas"):
            for meta in existing["metadatas"]:
                if meta.get("content_hash") == c_hash:
                    return {"status": "duplicate", "url": final_url, "title": title,
                            "content_hash": c_hash,
                            "existing_url": meta.get("url", "unknown")}
    except Exception:
        pass  # If check fails, proceed with upsert

    # Build documents, metadatas, ids
    documents = []
    metadatas = []
    ids = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for i, chunk in enumerate(chunks):
        chunk_id = f"web_{c_hash}_{i}"
        documents.append(chunk)
        metadatas.append({
            "url": final_url,
            "title": title[:200],
            "chunk_index": i,
            "total_chunks": len(chunks),
            "indexed_at": now,
            "content_hash": c_hash,
            "word_count": len(chunk.split()),
        })
        ids.append(chunk_id)

    memory_socket.upsert("web_pages", documents, metadatas, ids)

    return {
        "status": "indexed",
        "url": final_url,
        "title": title,
        "chunks": len(chunks),
        "words": total_words,
        "quality_score": score,
        "content_hash": c_hash,
    }


def main():
    parser = argparse.ArgumentParser(description="Index a web page into LanceDB")
    parser.add_argument("url", help="URL to index")
    parser.add_argument("--preview", action="store_true",
                        help="Preview what would be indexed without storing")
    args = parser.parse_args()

    try:
        result = index_url(args.url, preview=args.preview)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error fetching {args.url}: {e.response.status_code}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    status = result["status"]
    if status == "rejected":
        print(f"REJECTED: {result['title']}")
        print(f"  URL: {result['url']}")
        print(f"  Reason: {result['reason']}")
        sys.exit(1)
    elif status == "duplicate":
        print(f"DUPLICATE: {result['title']}")
        print(f"  URL: {result['url']}")
        print(f"  Hash: {result['content_hash']}")
        print(f"  Already indexed from: {result.get('existing_url', 'unknown')}")
    elif status == "preview":
        print(f"PREVIEW: {result['title']}")
        print(f"  URL: {result['url']}")
        print(f"  Chunks: {result['chunks']}")
        print(f"  Words: {result['words']}")
        print(f"  Quality: {result['quality_score']}")
        print(f"  Hash: {result['content_hash']}")
        print(f"\n--- First chunk ---")
        print(result["first_chunk_preview"])
    elif status == "indexed":
        print(f"INDEXED: {result['title']}")
        print(f"  URL: {result['url']}")
        print(f"  Chunks: {result['chunks']}")
        print(f"  Words: {result['words']}")
        print(f"  Quality: {result['quality_score']}")
        print(f"  Hash: {result['content_hash']}")


if __name__ == "__main__":
    main()
