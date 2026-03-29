#!/usr/bin/env python3
"""BM25 + nomic embedding hybrid search for Skill MCP v2.

Provides three index classes:
- BM25Index: keyword search via rank_bm25
- EmbeddingIndex: semantic search via nomic-embed-text-v2-moe (lazy loaded)
- HybridSearch: combines both with configurable weights

Embedding model loads in background — BM25 works immediately,
semantic search activates once the model is ready.
"""

import logging
import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Lazy-loaded embedding model
_model = None
_model_failed = False


def _get_embedding_model():
    """Load nomic embedding model. Returns None if unavailable."""
    global _model, _model_failed
    if _model_failed:
        return None
    if _model is None:
        try:
            import torch

            torch.set_num_threads(2)
            torch.set_num_interop_threads(2)
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(
                "nomic-ai/nomic-embed-text-v2-moe", trust_remote_code=True
            )
            _model.half()  # FP32 → FP16: halves RAM (~5.3GB → ~2.7GB), ~0% quality loss
            logger.info("Embedding model loaded (FP16)")
        except Exception as e:
            logger.warning("Embedding model unavailable, BM25-only: %s", e)
            _model_failed = True
            return None
    return _model


class BM25Index:
    """Keyword search using BM25Okapi."""

    def __init__(self):
        self._names: list[str] = []
        self._corpus: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._dirty = True

    def add(self, name: str, text: str) -> None:
        """Add a skill to the index."""
        self._names.append(name)
        self._corpus.append(text.lower().split())
        self._dirty = True

    def _rebuild(self) -> None:
        if self._corpus:
            self._bm25 = BM25Okapi(self._corpus)
        self._dirty = False

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Search by keywords. Returns [(name, score), ...]."""
        if not query.strip() or not self._corpus:
            return []
        if self._dirty:
            self._rebuild()
        scores = self._bm25.get_scores(query.lower().split())
        ranked = sorted(zip(self._names, scores), key=lambda x: -x[1])
        return [(n, float(s)) for n, s in ranked[:top_k] if s > 0]


class EmbeddingIndex:
    """Semantic search using nomic-embed-text-v2-moe.

    add() never blocks on model loading — stores raw text.
    search() computes embeddings lazily when model is available.
    """

    def __init__(self):
        self._names: list[str] = []
        self._texts: list[str] = []
        self._embeddings: list[np.ndarray | None] = []

    def add(self, name: str, text: str) -> None:
        """Add a skill to the index. Never blocks on model loading."""
        self._names.append(name)
        self._texts.append(text)
        self._embeddings.append(None)

    def _ensure_embeddings(self) -> None:
        """Compute embeddings for any pending items if model is ready."""
        model = _get_embedding_model()
        if model is None:
            return
        for i, text in enumerate(self._texts):
            if self._embeddings[i] is None:
                self._embeddings[i] = model.encode(text, normalize_embeddings=True)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Search by semantic similarity. Returns [(name, score), ...]."""
        self._ensure_embeddings()
        valid = [(n, e) for n, e in zip(self._names, self._embeddings) if e is not None]
        if not valid:
            return []
        model = _get_embedding_model()
        if model is None:
            return []
        query_emb = model.encode(query, normalize_embeddings=True)
        scores = [float(np.dot(query_emb, emb)) for _, emb in valid]
        names = [n for n, _ in valid]
        ranked = sorted(zip(names, scores), key=lambda x: -x[1])
        return [(n, s) for n, s in ranked[:top_k]]


class HybridSearch:
    """Combined BM25 + embedding search with configurable weights."""

    def __init__(self, bm25_weight: float = 0.4, embedding_weight: float = 0.6):
        self.bm25 = BM25Index()
        self.embedding = EmbeddingIndex()
        self.bm25_weight = bm25_weight
        self.embedding_weight = embedding_weight

    def add(self, name: str, text: str) -> None:
        """Add a skill to both indexes. Never blocks on model loading."""
        self.bm25.add(name, text)
        self.embedding.add(name, text)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Hybrid search combining BM25 and embedding scores.

        BM25 scores are normalized to [0, 1] before combining.
        Falls back to BM25-only if embeddings aren't available yet.
        Returns [(name, combined_score), ...].
        """
        if not query.strip():
            return []

        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        emb_results = self.embedding.search(query, top_k=top_k * 2)

        # Normalize BM25 scores to [0, 1]
        bm25_scores = {}
        if bm25_results:
            max_bm25 = max(s for _, s in bm25_results) or 1.0
            bm25_scores = {n: s / max_bm25 for n, s in bm25_results}

        emb_scores = {n: s for n, s in emb_results}

        # If no embeddings yet, return BM25-only (normalized to [0, 1])
        if not emb_scores and bm25_scores:
            ranked = sorted(bm25_scores.items(), key=lambda x: -x[1])
            return ranked[:top_k]

        # Combine all skill names
        all_names = set(bm25_scores.keys()) | set(emb_scores.keys())
        combined = []
        for name in all_names:
            score = self.bm25_weight * bm25_scores.get(
                name, 0.0
            ) + self.embedding_weight * emb_scores.get(name, 0.0)
            combined.append((name, score))

        combined.sort(key=lambda x: -x[1])
        return combined[:top_k]
