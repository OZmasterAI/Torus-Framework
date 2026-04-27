#!/usr/bin/env python3
"""BM25 + optional NIM embedding hybrid search for Skill MCP v2.

Provides three index classes:
- BM25Index: keyword search via rank_bm25 (default, zero dependencies)
- EmbeddingIndex: semantic search via NVIDIA NIM API (opt-in, no local model)
- HybridSearch: combines both with configurable weights

BM25 is the default. Pass use_embeddings=True to HybridSearch to enable
NIM-based semantic search (requires nim_api_key in config.json).
"""

import json
import logging
import os

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_NIM_URL = "https://integrate.api.nvidia.com/v1/embeddings"
_NIM_MODEL = "nvidia/nv-embed-v1"
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude", "config.json")


def _get_nim_api_key():
    """Read NIM API key from config.json."""
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH) as f:
                return json.load(f).get("nim_api_key", "")
    except Exception:
        pass
    return os.environ.get("NIM_API_KEY", "")


def _nim_embed(texts):
    """Embed texts via NVIDIA NIM API. Returns list of numpy arrays or None on failure."""
    import requests

    key = _get_nim_api_key()
    if not key:
        logger.warning("NIM API key not configured, skipping embeddings")
        return None
    safe = [t if t and t.strip() else "[empty]" for t in texts]
    try:
        resp = requests.post(
            _NIM_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _NIM_MODEL,
                "input": safe,
                "input_type": "passage",
                "encoding_format": "float",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [np.array(d["embedding"], dtype=np.float32) for d in data["data"]]
    except Exception as e:
        logger.warning("NIM embed failed: %s", e)
        return None


class BM25Index:
    """Keyword search using BM25Okapi."""

    def __init__(self):
        self._names: list[str] = []
        self._corpus: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._dirty = True

    def add(self, name: str, text: str) -> None:
        self._names.append(name)
        self._corpus.append(text.lower().split())
        self._dirty = True

    def _rebuild(self) -> None:
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
        self._dirty = False

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not query.strip() or not self._corpus:
            return []
        if self._dirty:
            self._rebuild()
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(zip(self._names, scores), key=lambda x: -x[1])
        return [(n, float(s)) for n, s in ranked[:top_k] if s > 0]


class EmbeddingIndex:
    """Semantic search via NVIDIA NIM API (nv-embed-v1, 4096-dim).

    No local model — embeddings are computed via HTTP API call.
    """

    def __init__(self):
        self._names: list[str] = []
        self._texts: list[str] = []
        self._embeddings: list[np.ndarray | None] = []

    def add(self, name: str, text: str) -> None:
        self._names.append(name)
        self._texts.append(text)
        self._embeddings.append(None)

    def _ensure_embeddings(self) -> None:
        pending = [
            (i, self._texts[i])
            for i in range(len(self._texts))
            if self._embeddings[i] is None
        ]
        if not pending:
            return
        indices, texts = zip(*pending)
        vecs = _nim_embed(list(texts))
        if vecs is None:
            return
        for i, vec in zip(indices, vecs):
            self._embeddings[i] = vec

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        self._ensure_embeddings()
        valid = [(n, e) for n, e in zip(self._names, self._embeddings) if e is not None]
        if not valid:
            return []
        query_vecs = _nim_embed([query])
        if query_vecs is None:
            return []
        query_emb = query_vecs[0]
        names = [n for n, _ in valid]
        emb_matrix = np.stack([e for _, e in valid])
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        emb_matrix = emb_matrix / norms
        query_norm = np.linalg.norm(query_emb)
        if query_norm > 0:
            query_emb = query_emb / query_norm
        scores = emb_matrix @ query_emb
        ranked = sorted(zip(names, scores.tolist()), key=lambda x: -x[1])
        return [(n, s) for n, s in ranked[:top_k]]


class HybridSearch:
    """Combined BM25 + optional NIM embedding search.

    Default: BM25-only (use_embeddings=False).
    Set use_embeddings=True to add NIM semantic search.
    """

    def __init__(
        self,
        bm25_weight: float = 0.4,
        embedding_weight: float = 0.6,
        use_embeddings: bool = False,
    ):
        self.bm25 = BM25Index()
        self.embedding = EmbeddingIndex() if use_embeddings else None
        self.bm25_weight = bm25_weight
        self.embedding_weight = embedding_weight

    def add(self, name: str, text: str) -> None:
        self.bm25.add(name, text)
        if self.embedding is not None:
            self.embedding.add(name, text)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not query.strip():
            return []

        bm25_results = self.bm25.search(query, top_k=top_k * 2)

        if self.embedding is None:
            return bm25_results[:top_k]

        emb_results = self.embedding.search(query, top_k=top_k * 2)

        bm25_scores = {}
        if bm25_results:
            max_bm25 = max(s for _, s in bm25_results) or 1.0
            bm25_scores = {n: s / max_bm25 for n, s in bm25_results}

        emb_scores = {n: s for n, s in emb_results}

        if not emb_scores and bm25_scores:
            ranked = sorted(bm25_scores.items(), key=lambda x: -x[1])
            return ranked[:top_k]

        all_names = set(bm25_scores.keys()) | set(emb_scores.keys())
        combined = []
        for name in all_names:
            score = self.bm25_weight * bm25_scores.get(
                name, 0.0
            ) + self.embedding_weight * emb_scores.get(name, 0.0)
            combined.append((name, score))

        combined.sort(key=lambda x: -x[1])
        return combined[:top_k]
