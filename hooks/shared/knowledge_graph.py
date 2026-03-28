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

_DEFAULT_DB_PATH = os.path.expanduser("~/data/memory/knowledge_graph.db")


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

    def batch_get_entities(self, names):
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        rows = self._conn.execute(
            f"SELECT name, type, salience, mention_count, created_at, last_seen_at "
            f"FROM entities WHERE name IN ({placeholders})",
            list(names),
        ).fetchall()
        return {
            row[0]: {
                "name": row[0],
                "type": row[1],
                "salience": row[2],
                "mention_count": row[3],
                "created_at": row[4],
                "last_seen_at": row[5],
            }
            for row in rows
        }

    def batch_get_edges(self, entity_ids):
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        rows = self._conn.execute(
            f"SELECT from_id, to_id, relation_type, strength, activation_count, "
            f"co_occurrence_count, pmi, created_at, last_activated "
            f"FROM edges WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})",
            list(entity_ids) + list(entity_ids),
        ).fetchall()
        return [
            {
                "from_id": r[0],
                "to_id": r[1],
                "relation_type": r[2],
                "strength": r[3],
                "activation_count": r[4],
                "co_occurrence_count": r[5],
                "pmi": r[6],
                "created_at": r[7],
                "last_activated": r[8],
            }
            for r in rows
        ]

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
            INSERT INTO edges (from_id, to_id, relation_type, strength, activation_count, co_occurrence_count)
            VALUES (?, ?, ?, ?, 1, 1)
            ON CONFLICT(from_id, to_id, relation_type) DO UPDATE SET
                strength = MIN(1.0, strength + ? * (1.0 - strength)),
                activation_count = activation_count + 1,
                co_occurrence_count = co_occurrence_count + 1,
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

    def update_pmi(
        self, from_name: str, to_name: str, relation_type: str, total_memories: int
    ):
        """Compute and store PMI for an edge.

        PMI = log2( P(x,y) / (P(x) * P(y)) )
            = log2( co_count * total_memories / (mention_x * mention_y) )

        Skips silently if entity counts or co_occurrence_count are zero.
        """
        if total_memories < 2:
            return
        try:
            row = self._conn.execute(
                "SELECT co_occurrence_count FROM edges WHERE from_id=? AND to_id=? AND relation_type=?",
                (from_name, to_name, relation_type),
            ).fetchone()
            if not row or row[0] == 0:
                return
            co_count = row[0]

            fx = self._conn.execute(
                "SELECT mention_count FROM entities WHERE name=?", (from_name,)
            ).fetchone()
            fy = self._conn.execute(
                "SELECT mention_count FROM entities WHERE name=?", (to_name,)
            ).fetchone()
            if not fx or not fy or fx[0] == 0 or fy[0] == 0:
                return

            pmi = math.log2((co_count * total_memories) / (fx[0] * fy[0]))
            self._conn.execute(
                "UPDATE edges SET pmi=? WHERE from_id=? AND to_id=? AND relation_type=?",
                (pmi, from_name, to_name, relation_type),
            )
            self._conn.commit()
        except Exception:
            pass  # PMI computation failure is non-fatal

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

    # --- Memory link traversal (A-Mem interconnected network) ---

    def get_linked_memories(
        self, memory_id: str, max_depth: int = 2, relation_type: str = "linked_memory"
    ) -> List[Dict]:
        """Traverse linked_memory edges from a memory node via BFS.

        Returns list of connected memory IDs with depth and edge strength.
        Each entry: {"id": str, "depth": int, "strength": float}

        Used by A-Mem interconnected network to surface related memories.
        """
        visited: Dict[str, Dict] = {}
        frontier = [(memory_id, 0, 1.0)]  # (node, depth, cumulative_strength)

        while frontier:
            node, depth, cum_strength = frontier.pop(0)
            if node in visited:
                continue
            visited[node] = {"depth": depth, "strength": cum_strength}

            if depth >= max_depth:
                continue

            # Fetch neighbors via linked_memory edges (both directions)
            rows = self._conn.execute(
                "SELECT to_id, strength FROM edges "
                "WHERE from_id=? AND relation_type=? AND strength > 0 "
                "UNION "
                "SELECT from_id, strength FROM edges "
                "WHERE to_id=? AND relation_type=? AND strength > 0",
                (node, relation_type, node, relation_type),
            ).fetchall()

            for neighbor_id, edge_strength in rows:
                if neighbor_id not in visited:
                    frontier.append(
                        (neighbor_id, depth + 1, cum_strength * edge_strength)
                    )

        # Remove the seed node from results
        visited.pop(memory_id, None)

        results = [
            {"id": nid, "depth": info["depth"], "strength": round(info["strength"], 4)}
            for nid, info in visited.items()
        ]
        results.sort(key=lambda x: (-x["strength"], x["depth"]))
        return results

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

        seed_set = set(seed_entities)

        for hop in range(1, max_hops + 1):
            # Filter frontier to nodes above threshold
            active_frontier = [
                n for n in frontier if activations.get(n, 0.0) >= threshold
            ]
            if not active_frontier:
                break

            # Batch fetch all neighbors for this hop
            all_neighbors = self._get_neighbors_batch(active_frontier)
            decay = math.exp(-0.2 * hop)

            next_frontier = set()
            for node in active_frontier:
                source_act = activations.get(node, 0.0)
                neighbors = all_neighbors.get(node, [])
                degree = max(1, len(neighbors))

                for neighbor_name, edge_strength in neighbors:
                    if neighbor_name in seed_set:
                        continue
                    spread = source_act * decay * edge_strength / math.sqrt(1 + degree)
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

            # Normalize activations with tanh to bound PMI-driven accumulation
            activations = {
                k: math.tanh(v) if k not in seed_set else v
                for k, v in activations.items()
            }

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
        """Get all neighbors with effective edge weights (PMI-weighted or raw fallback).
        Filters out deactivated entities (salience=0)."""
        rows = self._conn.execute(
            "SELECT e.to_id, e.strength, e.pmi, e.co_occurrence_count FROM edges e "
            "LEFT JOIN entities ent ON ent.name = e.to_id "
            "WHERE e.from_id=? AND e.strength > 0 AND COALESCE(ent.salience, 0.5) > 0 "
            "UNION "
            "SELECT e.from_id, e.strength, e.pmi, e.co_occurrence_count FROM edges e "
            "LEFT JOIN entities ent ON ent.name = e.from_id "
            "WHERE e.to_id=? AND e.strength > 0 AND COALESCE(ent.salience, 0.5) > 0",
            (node, node),
        ).fetchall()
        result = []
        for neighbor_name, strength, pmi, co_count in rows:
            co_count = co_count or 0
            if co_count == 0 or pmi is None:
                # Legacy edge (no PMI data yet) — use raw strength as fallback
                effective = strength
            elif pmi > 0.0:
                # PMI-weighted: clamp with tanh to keep effective in [0, strength]
                effective = strength * math.tanh(pmi / 2.0)
            else:
                # pmi <= 0.0: at-chance or anti-correlated — block this path
                effective = 0.0
            result.append((neighbor_name, effective))
        return result

    def _get_neighbors_batch(self, nodes):
        """Batch neighbor lookup for multiple nodes. More efficient than per-node queries."""
        if not nodes:
            return {}
        placeholders = ",".join("?" for _ in nodes)
        rows = self._conn.execute(
            f"SELECT e.from_id, e.to_id, e.strength, e.pmi, e.co_occurrence_count FROM edges e "
            f"LEFT JOIN entities ent ON ent.name = e.to_id "
            f"WHERE e.from_id IN ({placeholders}) AND e.strength > 0 AND COALESCE(ent.salience, 0.5) > 0 "
            f"UNION "
            f"SELECT e.to_id, e.from_id, e.strength, e.pmi, e.co_occurrence_count FROM edges e "
            f"LEFT JOIN entities ent ON ent.name = e.from_id "
            f"WHERE e.to_id IN ({placeholders}) AND e.strength > 0 AND COALESCE(ent.salience, 0.5) > 0",
            list(nodes) + list(nodes),
        ).fetchall()
        result = {n: [] for n in nodes}
        for source, neighbor, strength, pmi, co_count in rows:
            co_count = co_count or 0
            if co_count == 0 or pmi is None:
                effective = strength
            elif pmi > 0.0:
                effective = strength * math.tanh(pmi / 2.0)
            else:
                effective = 0.0
            if source in result:
                result[source].append((neighbor, effective))
        return result

    # --- Edge decay and pattern detection ---

    def decay_edges(self, half_life_hours: float = 168.0) -> Dict:
        """Apply time-based decay to all edges. Prune edges below 0.05.

        Uses SQL for bulk computation where possible.
        Returns dict with 'decayed' and 'pruned' counts.
        """
        import time as _time

        now = _time.time()
        # Compute decay factor threshold: what age makes strength * factor < 0.05?
        # For very old edges, prune directly via SQL
        max_age_hours = half_life_hours * math.log2(1.0 / 0.05)  # ~4.3 half-lives
        max_age_secs = max_age_hours * 3600

        # Prune edges older than max_age (they'd all decay below 0.05 anyway)
        pruned = self._conn.execute(
            "DELETE FROM edges WHERE (? - last_activated) > ?",
            (now, max_age_secs),
        ).rowcount

        # Decay remaining edges in-memory (only those that survive the prune)
        rows = self._conn.execute(
            "SELECT from_id, to_id, relation_type, strength, last_activated FROM edges"
        ).fetchall()
        to_prune = []
        to_update = []
        for from_id, to_id, rel, strength, last_act in rows:
            hours_since = max(0, (now - float(last_act)) / 3600)
            factor = math.pow(0.5, hours_since / half_life_hours)
            new_strength = strength * factor
            if new_strength < 0.05:
                to_prune.append((from_id, to_id, rel))
            else:
                to_update.append((new_strength, from_id, to_id, rel))
        if to_prune:
            self._conn.executemany(
                "DELETE FROM edges WHERE from_id=? AND to_id=? AND relation_type=?",
                to_prune,
            )
        if to_update:
            self._conn.executemany(
                "UPDATE edges SET strength=? WHERE from_id=? AND to_id=? AND relation_type=?",
                to_update,
            )
        self._conn.commit()
        return {"decayed": len(to_update), "pruned": pruned + len(to_prune)}

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

    def normalize_entity_name(self, name: str) -> str:
        """Normalize entity name for consistent matching.

        Lowercases, strips whitespace, collapses internal spaces.
        """
        if not name:
            return ""
        return " ".join(name.lower().strip().split())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self._conn.close()
