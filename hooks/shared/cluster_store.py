"""ClusterStore — SQLite-backed incremental clustering.

Extracted from memory_server.py as part of Memory v2 Layered Redesign.

Public API:
    from shared.cluster_store import ClusterStore, cluster_label
    CLUSTER_THRESHOLD = 0.7
"""

import os
import sqlite3
from collections import Counter
from datetime import datetime

from shared.error_normalizer import fnv1a_hash

# Cosine similarity threshold for cluster assignment
CLUSTER_THRESHOLD = 0.7


def cluster_label(content: str) -> str:
    """Extract top-3 meaningful words from content for a cluster label."""
    import re as _re_cl

    _stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "will",
        "would",
        "could",
        "should",
        "their",
        "there",
        "they",
        "which",
        "when",
        "what",
        "where",
        "than",
        "then",
        "also",
        "about",
        "into",
        "more",
        "some",
        "such",
        "only",
        "other",
        "each",
        "just",
        "like",
        "over",
        "very",
        "after",
        "before",
        "between",
        "under",
        "again",
        "does",
        "done",
        "make",
        "made",
        "most",
        "much",
        "must",
        "need",
        "none",
        "true",
        "false",
    }
    words = _re_cl.findall(r"[a-zA-Z_]{4,}", content.lower())
    counts = Counter(w for w in words if w not in _stop)
    top = [w for w, _ in counts.most_common(3)]
    return " / ".join(top) if top else "misc"


class ClusterStore:
    """SQLite-backed centroid store for incremental clustering.

    Stores cluster centroids as normalized float32 numpy arrays (nv-embed-v1 4096-dim).
    Provides fast nearest-centroid lookup via in-memory cache.
    """

    def __init__(self, db_path: str, threshold: float = CLUSTER_THRESHOLD):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._threshold = threshold
        self._create_tables()
        self._cache = None  # List of (cluster_id, centroid_np, member_count) or None

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS clusters (
                cluster_id TEXT PRIMARY KEY,
                centroid BLOB NOT NULL,
                member_count INTEGER DEFAULT 0,
                label TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        self._conn.commit()

    def _load_cache(self):
        import numpy as np

        rows = self._conn.execute(
            "SELECT cluster_id, centroid, member_count FROM clusters"
        ).fetchall()
        self._cache = [
            (cid, np.frombuffer(blob, dtype=np.float32).copy(), count)
            for cid, blob, count in rows
        ]

    def assign(self, vec_list: list, content: str = "") -> str:
        """Assign a vector to the nearest cluster or create a new one.

        Args:
            vec_list: embedding as list of floats (dimension matches model)
            content: original text (used for label generation)

        Returns cluster_id string.
        """
        import numpy as np

        vec = np.array(vec_list, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm < 1e-10:
            return ""
        vec_norm = vec / norm

        if self._cache is None:
            self._load_cache()

        best_id = None
        best_sim = -1.0
        best_idx = -1

        for i, (cid, c_vec, _count) in enumerate(self._cache):
            sim = float(np.dot(vec_norm, c_vec))
            if sim > best_sim:
                best_sim = sim
                best_id = cid
                best_idx = i

        now = datetime.now().isoformat()

        if best_id is not None and best_sim >= self._threshold:
            # Join existing cluster, update centroid via running mean
            cid, c_vec, count = self._cache[best_idx]
            new_count = count + 1
            new_centroid = (c_vec * count + vec_norm) / new_count
            c_norm = np.linalg.norm(new_centroid)
            if c_norm > 1e-10:
                new_centroid = new_centroid / c_norm

            label_update = ""
            if new_count % 10 == 0:
                label_update = cluster_label(content)

            self._conn.execute(
                "UPDATE clusters SET centroid=?, member_count=?, updated_at=? WHERE cluster_id=?",
                (new_centroid.astype(np.float32).tobytes(), new_count, now, best_id),
            )
            if label_update:
                self._conn.execute(
                    "UPDATE clusters SET label=? WHERE cluster_id=?",
                    (label_update, best_id),
                )
            self._conn.commit()
            self._cache[best_idx] = (cid, new_centroid, new_count)
            return best_id
        else:
            # Create new cluster
            new_id = f"cl_{fnv1a_hash(content)}"
            label = cluster_label(content)
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO clusters (cluster_id, centroid, member_count, label, created_at, updated_at) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (new_id, vec_norm.astype(np.float32).tobytes(), label, now, now),
            )
            self._conn.commit()
            if self._cache is not None and cursor.rowcount > 0:
                self._cache.append((new_id, vec_norm, 1))
            return new_id

    def close(self):
        self._conn.close()
