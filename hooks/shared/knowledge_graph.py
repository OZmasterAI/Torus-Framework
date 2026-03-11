"""Knowledge Graph for the Torus Memory System.

SQLite-backed graph storing entities and edges with Hebbian co-retrieval
strengthening and spreading activation for enriched search.

Public API:
    from shared.knowledge_graph import KnowledgeGraph
"""

import math
import os
import sqlite3
from itertools import combinations
from typing import Dict, List, Optional, Tuple

_DEFAULT_DB_PATH = os.path.expanduser("~/.claude/data/memory/knowledge_graph.db")


class KnowledgeGraph:
    """SQLite-backed knowledge graph with Hebbian learning."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL DEFAULT 'Concept',
                salience REAL NOT NULL DEFAULT 0.5,
                mention_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                last_seen_at REAL NOT NULL DEFAULT (strftime('%s','now'))
            );
            CREATE TABLE IF NOT EXISTS edges (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT 'co_retrieved',
                strength REAL NOT NULL DEFAULT 0.0,
                activation_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
                last_activated REAL NOT NULL DEFAULT (strftime('%s','now')),
                PRIMARY KEY (from_id, to_id, relation_type)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
        """)
        self._conn.commit()
        # Migration: add PMI and co_occurrence_count columns to edges (fail-open)
        for _col_sql in [
            "ALTER TABLE edges ADD COLUMN co_occurrence_count INTEGER DEFAULT 0",
            "ALTER TABLE edges ADD COLUMN pmi REAL",  # NULL = not yet computed
        ]:
            try:
                self._conn.execute(_col_sql)
                self._conn.commit()
            except Exception:
                pass  # Column already exists

    # --- Entity operations ---

    def upsert_entity(
        self, name: str, entity_type: str = "Concept", salience: float = 0.5
    ):
        """Insert or update an entity, incrementing mention count."""
        self._conn.execute(
            """
            INSERT INTO entities (name, type, salience, mention_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                mention_count = mention_count + 1,
                last_seen_at = strftime('%s','now'),
                salience = MAX(salience, ?)
        """,
            (name, entity_type, salience, salience),
        )
        self._conn.commit()

    def entity_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()
        return row[0] if row else 0

    # --- Edge operations ---

    def add_edge(
        self,
        from_name: str,
        to_name: str,
        relation_type: str = "co_occurs",
        strength: float = 0.1,
    ):
        """Create or strengthen an edge between two entities."""
        self._conn.execute(
            """
            INSERT INTO edges (from_id, to_id, relation_type, strength, activation_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(from_id, to_id, relation_type) DO UPDATE SET
                strength = MIN(1.0, strength + ? * (1.0 - strength)),
                activation_count = activation_count + 1,
                last_activated = strftime('%s','now')
        """,
            (from_name, to_name, relation_type, strength, strength),
        )
        self._conn.commit()

    def get_edge_strength(
        self, from_id: str, to_id: str, relation_type: Optional[str] = None
    ) -> float:
        """Get edge strength between two nodes. Checks both directions."""
        if relation_type:
            row = self._conn.execute(
                "SELECT strength FROM edges WHERE from_id=? AND to_id=? AND relation_type=?",
                (from_id, to_id, relation_type),
            ).fetchone()
            if row:
                return row[0]
            row = self._conn.execute(
                "SELECT strength FROM edges WHERE from_id=? AND to_id=? AND relation_type=?",
                (to_id, from_id, relation_type),
            ).fetchone()
            return row[0] if row else 0.0
        else:
            row = self._conn.execute(
                "SELECT MAX(strength) FROM edges WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
                (from_id, to_id, to_id, from_id),
            ).fetchone()
            return row[0] if row and row[0] is not None else 0.0

    def edge_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()
        return row[0] if row else 0

    def strengthen_coretrieval(self, memory_ids: List[str]):
        """Hebbian: strengthen edges between all pairs of co-retrieved memories."""
        if len(memory_ids) < 2:
            return
        for a, b in combinations(memory_ids, 2):
            canonical = (min(a, b), max(a, b))
            self._conn.execute(
                """
                INSERT INTO edges (from_id, to_id, relation_type, strength, activation_count)
                VALUES (?, ?, 'co_retrieved', 0.1, 1)
                ON CONFLICT(from_id, to_id, relation_type) DO UPDATE SET
                    strength = MIN(1.0, strength + 0.1 * (1.0 - strength)),
                    activation_count = activation_count + 1,
                    last_activated = strftime('%s','now')
            """,
                canonical,
            )
        self._conn.commit()

    # --- Cleanup operations ---

    def transfer_edges(self, from_entity: str, to_entity: str):
        """Transfer all edges from one entity to another (for dedup merge)."""
        # Repoint edges where from_entity is the source
        self._conn.execute(
            "UPDATE OR IGNORE edges SET from_id=? WHERE from_id=?",
            (to_entity, from_entity),
        )
        # Repoint edges where from_entity is the target
        self._conn.execute(
            "UPDATE OR IGNORE edges SET to_id=? WHERE to_id=?", (to_entity, from_entity)
        )
        # Clean up any orphaned edges (conflicts from OR IGNORE)
        self._conn.execute(
            "DELETE FROM edges WHERE from_id=? OR to_id=?", (from_entity, from_entity)
        )
        self._conn.commit()

    def remove_entity_edges(self, entity_name: str):
        """Remove all edges to/from an entity."""
        self._conn.execute(
            "DELETE FROM edges WHERE from_id=? OR to_id=?", (entity_name, entity_name)
        )
        self._conn.commit()

    def deactivate_entity(self, entity_name: str):
        """Set entity salience to 0 (soft delete for quarantine)."""
        self._conn.execute(
            "UPDATE entities SET salience=0.0 WHERE name=?", (entity_name,)
        )
        self._conn.commit()

    # --- Spreading activation ---

    def spreading_activation(
        self,
        seed_entities: List[str],
        max_hops: int = 4,
        threshold: float = 0.005,
    ) -> List[Dict]:
        """BFS spreading activation from seed entities over the graph.

        Returns list of activated entities sorted by activation descending.
        Each entry: {"name": str, "activation": float, "hops": int}
        """
        activations: Dict[str, float] = {}
        hops_map: Dict[str, int] = {}

        # Seed entities start with activation 1.0
        for entity in seed_entities:
            activations[entity] = 1.0
            hops_map[entity] = 0

        frontier = set(seed_entities)

        for hop in range(1, max_hops + 1):
            next_frontier = set()
            for node in frontier:
                source_act = activations.get(node, 0.0)
                if source_act < threshold:
                    continue

                # Get neighbors
                neighbors = self._get_neighbors(node)
                degree = max(1, len(neighbors))

                for neighbor_name, edge_strength in neighbors:
                    if neighbor_name in seed_entities:
                        continue  # don't re-activate seeds
                    spread = (
                        source_act
                        * math.exp(-0.2 * hop)
                        * edge_strength
                        / math.sqrt(1 + degree)
                    )
                    if spread < threshold:
                        continue
                    old = activations.get(neighbor_name, 0.0)
                    activations[neighbor_name] = old + spread
                    if neighbor_name not in hops_map:
                        hops_map[neighbor_name] = hop
                    next_frontier.add(neighbor_name)

            frontier = next_frontier
            if not frontier:
                break

            # Normalize if max activation > 2.0
            max_act = max(activations.values()) if activations else 0
            if max_act > 2.0:
                factor = 2.0 / max_act
                activations = {k: v * factor for k, v in activations.items()}

            # Early termination: <5% new entities after hop 3
            if hop >= 3 and len(next_frontier) < 0.05 * len(activations):
                break

        # Build results excluding seeds
        results = []
        for name, activation in activations.items():
            if name in seed_entities:
                continue
            if activation >= threshold:
                results.append(
                    {
                        "name": name,
                        "activation": activation,
                        "hops": hops_map.get(name, 0),
                    }
                )
        results.sort(key=lambda x: x["activation"], reverse=True)
        return results

    def _get_neighbors(self, node: str) -> List[Tuple[str, float]]:
        """Get all neighbors with edge strengths (both directions)."""
        rows = self._conn.execute(
            "SELECT to_id, strength FROM edges WHERE from_id=? AND strength > 0 "
            "UNION "
            "SELECT from_id, strength FROM edges WHERE to_id=? AND strength > 0",
            (node, node),
        ).fetchall()
        return rows

    # --- Edge decay and pattern detection ---

    def decay_edges(self, half_life_hours: float = 168.0) -> Dict:
        """Apply time-based decay to all edges. Prune edges below 0.05.

        Returns dict with 'decayed' and 'pruned' counts.
        """
        import time as _time

        now = _time.time()
        rows = self._conn.execute(
            "SELECT from_id, to_id, relation_type, strength, last_activated FROM edges"
        ).fetchall()
        decayed = 0
        pruned = 0
        for from_id, to_id, rel, strength, last_act in rows:
            hours_since = max(0, (now - float(last_act)) / 3600)
            factor = math.pow(0.5, hours_since / half_life_hours)
            new_strength = strength * factor
            if new_strength < 0.05:
                self._conn.execute(
                    "DELETE FROM edges WHERE from_id=? AND to_id=? AND relation_type=?",
                    (from_id, to_id, rel),
                )
                pruned += 1
            else:
                self._conn.execute(
                    "UPDATE edges SET strength=? WHERE from_id=? AND to_id=? AND relation_type=?",
                    (new_strength, from_id, to_id, rel),
                )
                decayed += 1
        self._conn.commit()
        return {"decayed": decayed, "pruned": pruned}

    def get_high_activation_clusters(self, min_activation: int = 5) -> List[set]:
        """Find connected components of edges with activation_count >= threshold.

        Returns list of sets, each set containing entity names in a cluster (3+ nodes).
        Sorted by cluster size descending.
        """
        rows = self._conn.execute(
            "SELECT from_id, to_id FROM edges WHERE activation_count >= ?",
            (min_activation,),
        ).fetchall()
        # Union-find
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for from_id, to_id in rows:
            parent.setdefault(from_id, from_id)
            parent.setdefault(to_id, to_id)
            union(from_id, to_id)

        # Group by root
        groups: Dict[str, set] = {}
        for node in parent:
            root = find(node)
            groups.setdefault(root, set()).add(node)

        clusters = [g for g in groups.values() if len(g) >= 3]
        clusters.sort(key=len, reverse=True)
        return clusters

    def boost_entity_salience(self, names: List[str], delta: float = 0.1):
        """Boost salience for a list of entity names."""
        for name in names:
            self._conn.execute(
                "UPDATE entities SET salience = MIN(1.0, salience + ?) WHERE name=?",
                (delta, name),
            )
        self._conn.commit()

    def close(self):
        self._conn.close()
