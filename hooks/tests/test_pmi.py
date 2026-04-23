#!/usr/bin/env python3
"""Tests for Feature #4: PMI Filtering for Knowledge Graph Edges."""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.harness import test, MEMORY_SERVER_RUNNING

print("\n--- PMI Filtering: Knowledge Graph ---")

from shared.knowledge_graph import KnowledgeGraph

# --- Test 1: New columns exist after KnowledgeGraph init ---
_kg = KnowledgeGraph(":memory:")
_cols = {r[1] for r in _kg._conn.execute("PRAGMA table_info(edges)").fetchall()}
test(
    "PMI: edges table has co_occurrence_count column",
    "co_occurrence_count" in _cols,
    f"columns: {_cols}",
)
test(
    "PMI: edges table has pmi column",
    "pmi" in _cols,
    f"columns: {_cols}",
)

# --- Test 2: add_edge increments co_occurrence_count ---
_kg2 = KnowledgeGraph(":memory:")
_kg2.upsert_entity("alpha")
_kg2.upsert_entity("beta")
_kg2.add_edge("alpha", "beta", "co_occurs")
_kg2.add_edge("alpha", "beta", "co_occurs")  # second co-occurrence
_row = _kg2._conn.execute(
    "SELECT co_occurrence_count FROM edges WHERE from_id='alpha' AND to_id='beta'"
).fetchone()
test(
    "PMI: co_occurrence_count increments on add_edge",
    _row is not None and _row[0] == 2,
    f"co_occurrence_count={_row[0] if _row else None}",
)

# --- Test 3: PMI math correctness ---
# A in 50% of 100 memories (mention_count=50), B in 50%, co_occur 25x
# PMI = log2(25 * 100 / (50 * 50)) = log2(1.0) = 0.0
_kg3 = KnowledgeGraph(":memory:")
# Manually set mention counts
_kg3._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('X', 50)")
_kg3._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('Y', 50)")
_kg3._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count) "
    "VALUES ('X', 'Y', 'co_occurs', 0.5, 25)"
)
_kg3._conn.commit()
_kg3.update_pmi("X", "Y", "co_occurs", 100)
_pmi_row = _kg3._conn.execute(
    "SELECT pmi FROM edges WHERE from_id='X' AND to_id='Y'"
).fetchone()
test(
    "PMI: at-chance co-occurrence gives PMI=0.0",
    _pmi_row is not None and abs(_pmi_row[0]) < 0.01,
    f"pmi={_pmi_row[0] if _pmi_row else None}",
)

# X in 50%, Y in 50%, co_occur 50x — PMI = log2(50*100/(50*50)) = log2(2.0) = 1.0
_kg4 = KnowledgeGraph(":memory:")
_kg4._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('P', 50)")
_kg4._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('Q', 50)")
_kg4._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count) "
    "VALUES ('P', 'Q', 'co_occurs', 0.5, 50)"
)
_kg4._conn.commit()
_kg4.update_pmi("P", "Q", "co_occurs", 100)
_pmi_row2 = _kg4._conn.execute(
    "SELECT pmi FROM edges WHERE from_id='P' AND to_id='Q'"
).fetchone()
test(
    "PMI: 2x above-chance co-occurrence gives PMI≈1.0",
    _pmi_row2 is not None and abs(_pmi_row2[0] - 1.0) < 0.01,
    f"pmi={_pmi_row2[0] if _pmi_row2 else None}",
)

# --- Test 4: Spreading activation uses PMI-weighted edges ---
# Entity A -> B (strong PMI=2.0), A -> C (legacy, no PMI data)
_kg5 = KnowledgeGraph(":memory:")
_kg5._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('A', 10)")
_kg5._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('B', 10)")
_kg5._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('C', 10)")
# Edge A->B with PMI=2.0 (computed)
_kg5._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count, pmi) "
    "VALUES ('A', 'B', 'co_occurs', 0.5, 5, 2.0)"
)
# Edge A->C legacy (co_occurrence_count=0, pmi=NULL) — raw strength fallback
_kg5._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count) "
    "VALUES ('A', 'C', 'co_occurs', 0.3, 0)"
)
_kg5._conn.commit()

_neighbors = _kg5._get_neighbors("A")
_neighbor_map = {name: weight for name, weight in _neighbors}
test(
    "PMI: positive PMI edge has non-zero effective weight",
    "B" in _neighbor_map and _neighbor_map["B"] > 0.0,
    f"B weight={_neighbor_map.get('B')}, raw_strength=0.5",
)
test(
    "PMI: legacy edge (co_count=0) falls back to raw strength",
    "C" in _neighbor_map and abs(_neighbor_map["C"] - 0.3) < 0.01,
    f"C weight={_neighbor_map.get('C')}, expected raw=0.3",
)

# --- Test 5: Negative PMI blocks edge (effective=0) ---
_kg6 = KnowledgeGraph(":memory:")
_kg6._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count, pmi) "
    "VALUES ('M', 'N', 'co_occurs', 0.8, 3, -1.5)"
)
_kg6._conn.commit()
_neg_neighbors = {name: w for name, w in _kg6._get_neighbors("M")}
test(
    "PMI: negative PMI edge is blocked (effective=0)",
    "N" in _neg_neighbors and _neg_neighbors["N"] == 0.0,
    f"N weight={_neg_neighbors.get('N')}",
)

# --- Test 6: update_pmi is fail-open for missing entities ---
_kg7 = KnowledgeGraph(":memory:")
_kg7._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count) "
    "VALUES ('ghost', 'entity', 'co_occurs', 0.5, 5)"
)
_kg7._conn.commit()
try:
    _kg7.update_pmi("ghost", "entity", "co_occurs", 100)
    _no_crash = True
except Exception as e:
    _no_crash = False
test(
    "PMI: update_pmi is fail-open when entities missing",
    _no_crash,
    "should not raise exception",
)

# --- Test 7: Spreading activation result with PMI-weighted graph ---
_kg8 = KnowledgeGraph(":memory:")
_kg8._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('seed', 10)")
_kg8._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('related', 10)")
_kg8._conn.execute("INSERT INTO entities (name, mention_count) VALUES ('noise', 10)")
# Seed -> related: high PMI (2.0)
_kg8._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count, pmi) "
    "VALUES ('seed', 'related', 'co_occurs', 0.5, 5, 2.0)"
)
# Seed -> noise: negative PMI (blocked)
_kg8._conn.execute(
    "INSERT INTO edges (from_id, to_id, relation_type, strength, co_occurrence_count, pmi) "
    "VALUES ('seed', 'noise', 'co_occurs', 0.8, 2, -0.5)"
)
_kg8._conn.commit()
_activated = _kg8.spreading_activation(["seed"])
_activated_names = {a["name"] for a in _activated}
test(
    "PMI: spreading activation reaches positive-PMI neighbor",
    "related" in _activated_names,
    f"activated: {_activated_names}",
)
test(
    "PMI: spreading activation blocks negative-PMI neighbor",
    "noise" not in _activated_names,
    f"activated: {_activated_names}",
)
