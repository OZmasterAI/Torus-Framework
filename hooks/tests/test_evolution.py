"""Tests for A-Mem evolution (memory UPDATE mechanism) in WritePipeline.

Verifies that when a new memory is inserted, similar existing memories
get their tags updated based on shared entities (arxiv 2502.12110).
"""

import os
import sys
import pytest

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)
# Also add the actual hooks dir for this test
_real_hooks = os.path.expanduser("~/.claude/hooks")
if _real_hooks not in sys.path:
    sys.path.insert(0, _real_hooks)

from shared.write_pipeline import WritePipeline


class FakeCollection:
    def __init__(self):
        self._docs = {}
    def count(self):
        return len(self._docs)
    def upsert(self, documents, metadatas, ids):
        for i, doc_id in enumerate(ids):
            self._docs[doc_id] = {"document": documents[i], "metadata": metadatas[i]}
    def update(self, ids, metadatas):
        for i, doc_id in enumerate(ids):
            if doc_id in self._docs:
                self._docs[doc_id]["metadata"] = metadatas[i]
    def get(self, ids=None, include=None, limit=None):
        result_ids, result_docs, result_metas = [], [], []
        targets = ids if ids else list(self._docs.keys())
        for doc_id in targets:
            if doc_id in self._docs:
                result_ids.append(doc_id)
                result_docs.append(self._docs[doc_id]["document"])
                result_metas.append(self._docs[doc_id]["metadata"])
        return {"ids": result_ids, "documents": result_docs, "metadatas": result_metas}
    def query(self, query_texts, n_results=5, include=None):
        query_words = set(query_texts[0].lower().split())
        scored = []
        for doc_id, entry in self._docs.items():
            doc_words = set(entry["document"].lower().split())
            overlap = len(query_words & doc_words)
            total = max(len(query_words | doc_words), 1)
            similarity = overlap / total
            scored.append((doc_id, entry, 1.0 - similarity))
        scored.sort(key=lambda x: x[2])
        scored = scored[:n_results]
        result = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        for doc_id, entry, dist in scored:
            result["ids"][0].append(doc_id)
            result["documents"][0].append(entry["document"])
            result["metadatas"][0].append(entry["metadata"])
            result["distances"][0].append(dist)
        return result


class FakeTagIndex:
    def __init__(self):
        self._tags = {}
    def add_tags(self, doc_id, tags):
        self._tags[doc_id] = tags


def _make_pipeline(collection=None, config=None):
    col = collection or FakeCollection()
    tag_idx = FakeTagIndex()
    pipeline = WritePipeline(
        collection=col, tag_index=tag_idx, graph=None,
        config=config or {},
        helpers={
            "min_content_length": 20,
            "generate_id": lambda c: "id_" + str(abs(hash(c)))[:8],
            "summary_length": 120,
            "touch_memory_timestamp": lambda: None,
        },
    )
    return pipeline, col, tag_idx


def test_evolution_enriches_neighbor_tags():
    pipeline, col, tag_idx = _make_pipeline()
    # Use high-overlap content so FakeCollection word-overlap similarity exceeds 0.3 threshold
    col.upsert(
        documents=["LanceDB vector search supports fast semantic queries with embeddings and hybrid retrieval"],
        metadatas=[{"tags": "type:learning,area:backend", "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports fast semantic queries with embeddings and FTS hybrid mode",
        tags="type:feature,area:backend,area:memory-system",
    )
    assert result.get("id")
    neighbor_tags = col._docs["neighbor_1"]["metadata"]["tags"]
    assert "area:memory-system" in neighbor_tags or "type:feature" in neighbor_tags


def test_evolution_skips_self():
    pipeline, col, tag_idx = _make_pipeline()
    result = pipeline.write(
        content="Test memory about Python testing frameworks and pytest runner",
        tags="type:learning,area:testing",
    )
    doc_id = result.get("id")
    assert doc_id
    meta = col._docs[doc_id]["metadata"]
    # Quality scorer may append needs-enrichment; check our tags are present unchanged
    assert "type:learning" in meta["tags"]
    assert "area:testing" in meta["tags"]


def test_evolution_respects_similarity_threshold():
    pipeline, col, tag_idx = _make_pipeline()
    col.upsert(
        documents=["Cooking recipes for Italian pasta with tomato sauce and basil"],
        metadatas=[{"tags": "type:recipe", "context": ""}],
        ids=["unrelated_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports hybrid retrieval with FTS backend",
        tags="type:feature,area:backend",
    )
    assert col._docs["unrelated_1"]["metadata"]["tags"] == "type:recipe"


def test_evolution_max_3_updates():
    pipeline, col, tag_idx = _make_pipeline()
    for i in range(5):
        col.upsert(
            documents=[f"Memory system LanceDB vector search variant {i} with embeddings"],
            metadatas=[{"tags": "type:learning", "context": ""}],
            ids=[f"neighbor_{i}"],
        )
    result = pipeline.write(
        content="Memory system LanceDB vector search with embeddings and evolution",
        tags="type:feature,area:memory-system",
    )
    updated_count = sum(
        1 for i in range(5) if col._docs[f"neighbor_{i}"]["metadata"]["tags"] != "type:learning"
    )
    assert updated_count <= 3


def test_evolution_no_tag_duplication():
    pipeline, col, tag_idx = _make_pipeline()
    col.upsert(
        documents=["LanceDB vector search supports fast semantic queries with embeddings and hybrid retrieval"],
        metadatas=[{"tags": "type:feature,area:backend", "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports fast semantic queries with embeddings and FTS hybrid mode",
        tags="type:feature,area:backend,area:memory-system",
    )
    tag_list = [t.strip() for t in col._docs["neighbor_1"]["metadata"]["tags"].split(",")]
    assert tag_list.count("type:feature") <= 1
    assert tag_list.count("area:backend") <= 1


def test_evolution_skips_id_prefixes():
    pipeline, col, tag_idx = _make_pipeline()
    col.upsert(
        documents=["LanceDB vector search supports fast semantic queries with embeddings and hybrid retrieval"],
        metadatas=[{"tags": "type:learning", "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports fast semantic queries with embeddings and FTS hybrid mode",
        tags="type:feature,resolves:abc123,source:dual-write,cluster:c42",
    )
    neighbor_tags = col._docs["neighbor_1"]["metadata"]["tags"]
    assert "resolves:" not in neighbor_tags
    assert "source:" not in neighbor_tags
    assert "cluster:" not in neighbor_tags


def test_evolution_tag_cap():
    pipeline, col, tag_idx = _make_pipeline()
    long_tags = ",".join(f"tag{i}:value{i}" for i in range(35))  # ~420 chars, under 500
    col.upsert(
        documents=["LanceDB vector search supports fast semantic queries with embeddings and hybrid retrieval"],
        metadatas=[{"tags": long_tags, "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports fast semantic queries with embeddings and FTS hybrid mode",
        tags="type:feature,area:memory-system",
    )
    assert len(col._docs["neighbor_1"]["metadata"]["tags"]) <= 500


def test_evolution_no_tags_no_evolution():
    pipeline, col, tag_idx = _make_pipeline()
    col.upsert(
        documents=["LanceDB vector search is fast for semantic queries"],
        metadatas=[{"tags": "type:learning", "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports full-text search with hybrid mode",
        tags="",
    )
    assert col._docs["neighbor_1"]["metadata"]["tags"] == "type:learning"


def test_evolution_disabled_flag():
    pipeline, col, tag_idx = _make_pipeline(config={"enable_evolution": False})
    col.upsert(
        documents=["LanceDB vector search is fast for semantic queries"],
        metadatas=[{"tags": "type:learning", "context": ""}],
        ids=["neighbor_1"],
    )
    result = pipeline.write(
        content="LanceDB vector search supports full-text search with hybrid mode",
        tags="type:feature,area:memory-system",
    )
    assert col._docs["neighbor_1"]["metadata"]["tags"] == "type:learning"
    assert "evolved_neighbors" not in result


def test_evolution_fail_open():
    class BrokenQueryCollection(FakeCollection):
        _query_count = 0
        def query(self, *args, **kwargs):
            self._query_count += 1
            if self._query_count > 1:
                raise RuntimeError("Query backend is down")
            return super().query(*args, **kwargs)

    pipeline, col, tag_idx = _make_pipeline(collection=BrokenQueryCollection())
    result = pipeline.write(
        content="This memory should be stored despite evolution failure in query",
        tags="type:feature,area:testing",
    )
    assert result.get("id")
    assert not result.get("rejected")


def test_evolve_neighbors_direct():
    pipeline, col, tag_idx = _make_pipeline()
    col.upsert(
        documents=["LanceDB vector search with embeddings for semantic retrieval"],
        metadatas=[{"tags": "type:learning", "context": "search context"}],
        ids=["n1"],
    )
    count = pipeline._evolve_neighbors(
        doc_id="new_doc",
        content="LanceDB vector search with hybrid FTS and embeddings",
        context="testing evolution",
        tags="type:feature,area:memory-system",
        collection=col,
        tag_index=tag_idx,
    )
    assert isinstance(count, int)
    assert count >= 0
    n1_tags = col._docs["n1"]["metadata"]["tags"]
    assert "type:learning" in n1_tags
