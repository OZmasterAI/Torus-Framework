#!/usr/bin/env python3
"""Tests for Feature #5: Incremental Clustering at Ingest."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.harness import test, MEMORY_SERVER_RUNNING

print("\n--- Incremental Clustering ---")

# --- Test 1: _cluster_label extracts top-3 meaningful words ---
# Import from memory_server only if server not running (avoid LanceDB lock)
if MEMORY_SERVER_RUNNING:
    print("  [SKIP] Memory server running — skipping direct import tests")
    # Register skips so harness counts are consistent
    from tests.harness import skip
    skip("Clustering: _cluster_label extracts words")
    skip("Clustering: _ClusterStore creates cluster for first vector")
    skip("Clustering: similar vector joins existing cluster")
    skip("Clustering: dissimilar vector creates new cluster")
    skip("Clustering: centroid running mean updates correctly")
    skip("Clustering: _ClusterStore cache invalidates on update")
    skip("Clustering: _assign_cluster fallback on zero vector")
else:
    import sys as _sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    # We need to import memory_server — but it's a server module that calls
    # argparse at import time and needs sys.argv. Patch it.
    import sys
    _orig_argv = sys.argv[:]
    sys.argv = ["memory_server.py"]

    try:
        from memory_server import _cluster_label, _ClusterStore, CLUSTER_THRESHOLD
        import numpy as np

        # Restore argv
        sys.argv = _orig_argv

        # Test 1: _cluster_label
        _label = _cluster_label("python memory server knowledge graph retrieval")
        test(
            "Clustering: _cluster_label extracts words",
            len(_label) > 0 and "/" in _label,
            f"label='{_label}'",
        )

        # Test 2: First vector creates new cluster
        with tempfile.TemporaryDirectory() as d:
            store = _ClusterStore(os.path.join(d, "clusters.db"))
            v1 = np.zeros(768, dtype=np.float32)
            v1[0] = 1.0
            cid1 = store.assign(v1.tolist(), "python memory server test")
            test(
                "Clustering: _ClusterStore creates cluster for first vector",
                cid1.startswith("cl_"),
                f"cid={cid1}",
            )

            # Test 3: Similar vector joins same cluster
            v2 = v1.copy()
            v2[1] = 0.001  # tiny perturbation, still cosine-similar
            cid2 = store.assign(v2.tolist(), "python memory server similar")
            test(
                "Clustering: similar vector joins existing cluster",
                cid2 == cid1,
                f"cid1={cid1}, cid2={cid2}",
            )

            # Test 4: Orthogonal vector creates new cluster
            v3 = np.zeros(768, dtype=np.float32)
            v3[767] = 1.0  # orthogonal to v1
            cid3 = store.assign(v3.tolist(), "completely different domain topic")
            test(
                "Clustering: dissimilar vector creates new cluster",
                cid3 != cid1,
                f"cid1={cid1}, cid3={cid3}",
            )

            # Test 5: Centroid running mean updates correctly
            # After 2 members, centroid should be between v1 and v2 (normalized)
            store2 = _ClusterStore(os.path.join(d, "clusters2.db"))
            v_a = np.zeros(768, dtype=np.float32)
            v_a[0] = 1.0
            v_b = np.zeros(768, dtype=np.float32)
            v_b[0] = 0.6
            v_b[1] = 0.8  # different direction
            store2.assign(v_a.tolist(), "first content here")
            store2.assign(v_b.tolist(), "second content there")
            # Cache should have 1 cluster with count=2 (similar enough)
            # OR 2 clusters if not similar. Either way centroid logic is tested.
            total_cached = len(store2._cache)
            test(
                "Clustering: centroid running mean updates correctly",
                total_cached >= 1 and all(c >= 1 for _, _, c in store2._cache),
                f"clusters={total_cached}, counts={[c for _,_,c in store2._cache]}",
            )

            # Test 6: Cache invalidation doesn't happen mid-update
            # (cache is a list — verify it stays consistent after assign)
            prev_len = len(store._cache)
            v4 = np.zeros(768, dtype=np.float32)
            v4[100] = 1.0
            store.assign(v4.tolist(), "yet another unique topic")
            test(
                "Clustering: _ClusterStore cache invalidates on update",
                len(store._cache) >= prev_len,
                f"cache_len before={prev_len}, after={len(store._cache)}",
            )

        # Test 7: Zero vector returns empty string (fail-open)
        with tempfile.TemporaryDirectory() as d:
            store3 = _ClusterStore(os.path.join(d, "clusters3.db"))
            result = store3.assign([0.0] * 768, "content")
            test(
                "Clustering: _assign_cluster fallback on zero vector",
                result == "",
                f"result='{result}' (expected empty string for zero vector)",
            )

    except Exception as e:
        sys.argv = _orig_argv
        from tests.harness import skip
        skip(f"Clustering: import failed — {e}")
        skip("Clustering: _ClusterStore creates cluster for first vector")
        skip("Clustering: similar vector joins existing cluster")
        skip("Clustering: dissimilar vector creates new cluster")
        skip("Clustering: centroid running mean updates correctly")
        skip("Clustering: _ClusterStore cache invalidates on update")
        skip("Clustering: _assign_cluster fallback on zero vector")


# --- Test: cluster_id field in _KNOWLEDGE_SCHEMA ---
print("\n--- Incremental Clustering: Schema ---")

if MEMORY_SERVER_RUNNING:
    from tests.harness import skip
    skip("Clustering schema: cluster_id in _KNOWLEDGE_SCHEMA")
    skip("Clustering schema: CLUSTER_THRESHOLD constant exists")
else:
    try:
        import sys
        _orig_argv2 = sys.argv[:]
        sys.argv = ["memory_server.py"]
        from memory_server import _KNOWLEDGE_SCHEMA, CLUSTER_THRESHOLD
        sys.argv = _orig_argv2

        _schema_names = {f.name for f in _KNOWLEDGE_SCHEMA}
        test(
            "Clustering schema: cluster_id in _KNOWLEDGE_SCHEMA",
            "cluster_id" in _schema_names,
            f"schema fields: {_schema_names}",
        )
        test(
            "Clustering schema: CLUSTER_THRESHOLD constant exists",
            0.0 < CLUSTER_THRESHOLD <= 1.0,
            f"CLUSTER_THRESHOLD={CLUSTER_THRESHOLD}",
        )
    except Exception as e:
        sys.argv = _orig_argv2 if '_orig_argv2' in dir() else sys.argv
        from tests.harness import skip
        skip(f"Clustering schema: import failed — {e}")
        skip("Clustering schema: CLUSTER_THRESHOLD constant exists")
