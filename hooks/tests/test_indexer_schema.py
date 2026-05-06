"""Tests for Toroidal-Indexer SurrealDB schema (code_node + RELATE edges)."""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from surrealdb import Surreal

from shared.indexer_schema import (
    _node_key,
    connect_code_graph,
    dedup_nodes,
    delete_file_nodes,
    get_callers,
    get_readers,
    init_code_tables,
    relate,
    upsert_node,
)

SURREAL_URL = "ws://127.0.0.1:8822"


@pytest.fixture(scope="module")
def db():
    """Connect to SurrealDB with a unique test database, init tables, yield, cleanup."""
    test_db = f"test_indexer_{uuid.uuid4().hex[:8]}"
    conn = connect_code_graph(url=SURREAL_URL, database=test_db)
    init_code_tables(conn)
    yield conn
    conn.query(f"REMOVE DATABASE IF EXISTS {test_db}")


class TestInitCodeTables:
    def test_tables_exist(self, db):
        info = db.query("INFO FOR DB")
        for name in ("code_node", "calls", "imports", "reads", "writes", "implements"):
            assert name in info.get("tables", info.get("tb", {})), (
                f"table {name} missing"
            )

    def test_indexes_exist(self, db):
        info = db.query("INFO FOR TABLE code_node")
        indexes = info.get("indexes", info.get("ix", {}))
        assert "code_node_file" in indexes
        assert "code_node_name" in indexes

    def test_idempotent(self, db):
        init_code_tables(db)
        info = db.query("INFO FOR DB")
        assert info is not None


class TestUpsertNode:
    def test_creates_node(self, db):
        node_id = upsert_node(db, "proj", "src/main.py", "main", "function", 10)
        assert node_id is not None
        result = db.query("SELECT * FROM $id", {"id": node_id})
        assert len(result) == 1
        assert result[0]["name"] == "main"
        assert result[0]["file"] == "src/main.py"
        assert result[0]["type"] == "function"
        assert result[0]["line"] == 10

    def test_upsert_updates_existing(self, db):
        id1 = upsert_node(db, "proj", "a.py", "foo", "function", 5)
        id2 = upsert_node(db, "proj", "a.py", "foo", "function", 12)
        assert str(id1) == str(id2)
        result = db.query("SELECT * FROM $id", {"id": id1})
        assert result[0]["line"] == 12

    def test_deterministic_id(self, db):
        id1 = upsert_node(db, "proj", "x.py", "bar", "function", 1)
        id2 = upsert_node(db, "proj", "x.py", "bar", "function", 1)
        assert str(id1) == str(id2)

    def test_different_projects_different_ids(self, db):
        id1 = upsert_node(db, "projA", "x.py", "fn", "function", 1)
        id2 = upsert_node(db, "projB", "x.py", "fn", "function", 1)
        assert str(id1) != str(id2)


class TestRelate:
    def test_creates_edge(self, db):
        src = upsert_node(db, "proj", "caller.py", "do_stuff", "function", 1)
        tgt = upsert_node(db, "proj", "callee.py", "helper", "function", 5)
        edge = relate(db, src, "calls", tgt, confidence=1.0, source_line=3)
        assert edge is not None
        assert edge["confidence"] == 1.0
        assert edge["source_line"] == 3

    def test_forward_traversal(self, db):
        src = upsert_node(db, "proj", "fwd_a.py", "alpha", "function", 1)
        tgt = upsert_node(db, "proj", "fwd_b.py", "beta", "function", 1)
        relate(db, src, "calls", tgt, confidence=1.0, source_line=10)
        result = db.query("SELECT ->calls->code_node AS targets FROM $id", {"id": src})
        target_ids = [str(t) for t in result[0]["targets"]]
        assert str(tgt) in target_ids

    def test_reverse_traversal(self, db):
        src = upsert_node(db, "proj", "rev_a.py", "gamma", "function", 1)
        tgt = upsert_node(db, "proj", "rev_b.py", "delta", "function", 1)
        relate(db, src, "calls", tgt, confidence=1.0, source_line=20)
        result = db.query("SELECT <-calls<-code_node AS callers FROM $id", {"id": tgt})
        caller_ids = [str(c) for c in result[0]["callers"]]
        assert str(src) in caller_ids

    def test_reads_edge(self, db):
        src = upsert_node(db, "proj", "reader.py", "load_config", "function", 1)
        tgt = upsert_node(db, "proj", "state.py", "timeout", "field", 5)
        edge = relate(db, src, "reads", tgt, confidence=1.0, source_line=8)
        assert edge is not None

    def test_imports_edge(self, db):
        src = upsert_node(db, "proj", "mod_a.py", "mod_a.py", "file", 0)
        tgt = upsert_node(db, "proj", "mod_b.py", "mod_b.py", "file", 0)
        edge = relate(db, src, "imports", tgt, confidence=1.0, source_line=1)
        assert edge is not None

    def test_implements_edge(self, db):
        cls = upsert_node(db, "proj", "impl.py", "MyClass", "class", 1)
        base = upsert_node(db, "proj", "base.py", "BaseClass", "class", 1)
        edge = relate(db, cls, "implements", base, confidence=1.0, source_line=1)
        assert edge is not None

    def test_invalid_relation_rejected(self, db):
        src = upsert_node(db, "proj", "bad.py", "a", "function", 1)
        tgt = upsert_node(db, "proj", "bad.py", "b", "function", 2)
        with pytest.raises(ValueError, match="relation"):
            relate(db, src, "destroys", tgt, confidence=1.0, source_line=1)


class TestGetCallers:
    def test_returns_caller_info(self, db):
        caller = upsert_node(db, "proj", "gc_a.py", "caller_fn", "function", 10)
        target = upsert_node(db, "proj", "gc_b.py", "target_fn", "function", 20)
        relate(db, caller, "calls", target, confidence=1.0, source_line=15)
        callers = get_callers(db, target)
        assert len(callers) >= 1
        found = [c for c in callers if c["name"] == "caller_fn"]
        assert len(found) == 1
        assert found[0]["file"] == "gc_a.py"
        assert found[0]["confidence"] == 1.0

    def test_returns_empty_for_no_callers(self, db):
        isolated = upsert_node(db, "proj", "iso.py", "alone", "function", 1)
        callers = get_callers(db, isolated)
        assert callers == []

    def test_depth_2_traversal(self, db):
        a = upsert_node(db, "proj", "d2_a.py", "fn_a", "function", 1)
        b = upsert_node(db, "proj", "d2_b.py", "fn_b", "function", 1)
        c = upsert_node(db, "proj", "d2_c.py", "fn_c", "function", 1)
        relate(db, a, "calls", b, confidence=1.0, source_line=5)
        relate(db, b, "calls", c, confidence=1.0, source_line=10)
        callers = get_callers(db, c, depth=2)
        names = {c["name"] for c in callers}
        assert "fn_b" in names
        assert "fn_a" in names


class TestGetReaders:
    def test_returns_reader_info(self, db):
        reader = upsert_node(db, "proj", "gr_a.py", "read_fn", "function", 1)
        field = upsert_node(db, "proj", "gr_state.py", "config_key", "field", 5)
        relate(db, reader, "reads", field, confidence=1.0, source_line=8)
        readers = get_readers(db, field)
        assert len(readers) >= 1
        found = [r for r in readers if r["name"] == "read_fn"]
        assert len(found) == 1


class TestDeleteFileNodes:
    def test_removes_nodes_and_edges(self, db):
        n1 = upsert_node(db, "proj", "del_target.py", "fn1", "function", 1)
        n2 = upsert_node(db, "proj", "del_target.py", "fn2", "function", 10)
        other = upsert_node(db, "proj", "del_other.py", "caller", "function", 1)
        relate(db, other, "calls", n1, confidence=1.0, source_line=5)
        delete_file_nodes(db, "proj", "del_target.py")
        result = db.query(
            "SELECT * FROM code_node WHERE project=$proj AND file=$file",
            {"proj": "proj", "file": "del_target.py"},
        )
        assert len(result) == 0

    def test_does_not_affect_other_files(self, db):
        upsert_node(db, "proj", "keep_me.py", "safe_fn", "function", 1)
        upsert_node(db, "proj", "remove_me.py", "gone_fn", "function", 1)
        delete_file_nodes(db, "proj", "remove_me.py")
        result = db.query(
            "SELECT * FROM code_node WHERE project=$proj AND file=$file",
            {"proj": "proj", "file": "keep_me.py"},
        )
        assert len(result) >= 1


class TestRelateDedup:
    def test_relate_dedup_no_duplicates(self, db):
        """Calling relate() twice with same src/tgt/relation creates only one edge."""
        src = upsert_node(db, "proj", "dedup_a.py", "fn_dup", "function", 1)
        tgt = upsert_node(db, "proj", "dedup_b.py", "fn_tgt", "function", 1)
        relate(db, src, "calls", tgt, confidence=1.0, source_line=5)
        relate(db, src, "calls", tgt, confidence=0.9, source_line=5)
        edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": src, "tgt": tgt},
        )
        assert len(edges) == 1

    def test_dedup_index_exists_for_all_relations(self, db):
        """Each relation table has a dedup unique index on (in, out)."""
        for rel in ("calls", "imports", "reads", "writes", "implements"):
            info = db.query(f"INFO FOR TABLE {rel}")
            indexes = info.get("indexes", info.get("ix", {}))
            assert f"{rel}_dedup" in indexes, f"dedup index missing for {rel}"

    def test_dedup_different_pairs_allowed(self, db):
        """Different src/tgt pairs create separate edges."""
        a = upsert_node(db, "proj", "dedup_c.py", "fn_a", "function", 1)
        b = upsert_node(db, "proj", "dedup_d.py", "fn_b", "function", 1)
        c = upsert_node(db, "proj", "dedup_e.py", "fn_c", "function", 1)
        relate(db, a, "calls", b, confidence=1.0, source_line=1)
        relate(db, a, "calls", c, confidence=1.0, source_line=2)
        edges_b = db.query(
            "SELECT * FROM calls WHERE in=$a AND out=$b", {"a": a, "b": b}
        )
        edges_c = db.query(
            "SELECT * FROM calls WHERE in=$a AND out=$c", {"a": a, "c": c}
        )
        assert len(edges_b) == 1
        assert len(edges_c) == 1


class TestDedupNodes:
    def test_merges_duplicate_pair(self, db):
        canonical_key = _node_key("proj", "dn_a.py", "dup_fn")
        rogue_key = "rogue_dedup_test_01"
        from surrealdb import RecordID

        canonical_id = RecordID("code_node", canonical_key)
        rogue_id = RecordID("code_node", rogue_key)
        db.query(
            "UPSERT $id SET project='proj', file='dn_a.py', name='dup_fn', type='function', line=0",
            {"id": canonical_id},
        )
        db.query(
            "UPSERT $id SET project='proj', file='dn_a.py', name='dup_fn', type='function', line=42",
            {"id": rogue_id},
        )
        caller = upsert_node(db, "proj", "dn_caller.py", "caller", "function", 1)
        relate(db, caller, "calls", rogue_id, confidence=0.9, source_line=5)

        merged, migrated = dedup_nodes(db)
        assert merged >= 1
        assert migrated >= 1

        nodes = db.query(
            "SELECT * FROM code_node WHERE project='proj' AND file='dn_a.py' AND name='dup_fn'"
        )
        assert len(nodes) == 1
        assert nodes[0]["id"].id == canonical_key
        assert nodes[0]["line"] == 42

        edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": caller, "tgt": canonical_id},
        )
        assert len(edges) == 1

    def test_preserves_best_line(self, db):
        canonical_key = _node_key("proj", "dn_b.py", "lined_fn")
        rogue_key = "rogue_dedup_test_02"
        from surrealdb import RecordID

        db.query(
            "UPSERT $id SET project='proj', file='dn_b.py', name='lined_fn', type='function', line=0",
            {"id": RecordID("code_node", canonical_key)},
        )
        db.query(
            "UPSERT $id SET project='proj', file='dn_b.py', name='lined_fn', type='function', line=99",
            {"id": RecordID("code_node", rogue_key)},
        )
        dedup_nodes(db)
        nodes = db.query(
            "SELECT * FROM code_node WHERE project='proj' AND file='dn_b.py' AND name='lined_fn'"
        )
        assert len(nodes) == 1
        assert nodes[0]["line"] == 99

    def test_migrates_both_edge_directions(self, db):
        canonical_key = _node_key("proj", "dn_c.py", "bidir_fn")
        rogue_key = "rogue_dedup_test_03"
        from surrealdb import RecordID

        canonical_id = RecordID("code_node", canonical_key)
        rogue_id = RecordID("code_node", rogue_key)
        db.query(
            "UPSERT $id SET project='proj', file='dn_c.py', name='bidir_fn', type='function', line=0",
            {"id": canonical_id},
        )
        db.query(
            "UPSERT $id SET project='proj', file='dn_c.py', name='bidir_fn', type='function', line=10",
            {"id": rogue_id},
        )
        upstream = upsert_node(db, "proj", "dn_up.py", "upstream", "function", 1)
        downstream = upsert_node(db, "proj", "dn_down.py", "downstream", "function", 1)
        relate(db, upstream, "calls", rogue_id, confidence=0.9, source_line=3)
        relate(db, rogue_id, "calls", downstream, confidence=0.9, source_line=7)

        dedup_nodes(db)

        in_edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": upstream, "tgt": canonical_id},
        )
        assert len(in_edges) == 1
        out_edges = db.query(
            "SELECT * FROM calls WHERE in=$src AND out=$tgt",
            {"src": canonical_id, "tgt": downstream},
        )
        assert len(out_edges) == 1

    def test_no_dupes_is_noop(self, db):
        upsert_node(db, "proj", "dn_unique.py", "solo_fn", "function", 5)
        merged, migrated = dedup_nodes(db)
        nodes = db.query(
            "SELECT * FROM code_node WHERE project='proj' AND file='dn_unique.py' AND name='solo_fn'"
        )
        assert len(nodes) == 1


class TestConnectCodeGraph:
    def test_returns_connected_db(self, db):
        assert db is not None
        result = db.query("INFO FOR DB")
        assert result is not None
