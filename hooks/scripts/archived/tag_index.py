"""TagIndex — SQLite inverted tag index for boolean tag search.

Extracted from memory_server.py as part of Memory v2 Layered Redesign.

Public API:
    from shared.tag_index import TagIndex
"""

import sqlite3
import threading


class TagIndex:
    """Minimal SQLite tag index for boolean AND/OR tag search.

    LanceDB is the source of truth; this is a derived read-optimized cache.
    Keyword search is handled by LanceDB native FTS (BM25).
    """

    def __init__(self, db_path=":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS tags (
            memory_id TEXT,
            tag TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tags_mid ON tags(memory_id)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS sync_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        c.commit()

    def is_synced(self, lance_count):
        """Check if tag index is in sync with LanceDB by entry count."""
        row = self.conn.execute(
            "SELECT value FROM sync_meta WHERE key='sync_count'"
        ).fetchone()
        if row is None:
            return False
        return int(row[0]) == lance_count

    def _update_sync_count(self, count):
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('sync_count', ?)",
            (str(count),),
        )
        self.conn.commit()

    def reset_and_rebuild(self, lance_collection):
        """Drop all tables and rebuild from LanceDB (corruption recovery)."""
        self.conn.execute("DROP TABLE IF EXISTS tags")
        self.conn.execute("DROP TABLE IF EXISTS sync_meta")
        self.conn.commit()
        self._create_tables()
        return self.build_from_lance(lance_collection)

    def build_from_lance(self, lance_collection):
        """Rebuild tags table from LanceDB. Returns entry count."""
        count = lance_collection.count()
        if count == 0:
            return 0
        all_data = lance_collection.get(
            limit=count, include=["metadatas"], columns=["id", "tags"]
        )
        if not all_data or not all_data.get("ids"):
            return 0
        ids = all_data["ids"]
        metas = all_data.get("metadatas", [])

        with self._lock:
            self.conn.execute("DELETE FROM tags")
            rows = []
            for i, mid in enumerate(ids):
                meta = metas[i] if i < len(metas) else {}
                tags_str = meta.get("tags", "") if meta else ""
                if tags_str:
                    for tag in tags_str.split(","):
                        tag = tag.strip()
                        if tag:
                            rows.append((mid, tag))
            self.conn.executemany("INSERT INTO tags VALUES (?, ?)", rows)
            self._update_sync_count(len(ids))
        return len(ids)

    def add_tags(self, memory_id, tags_str):
        """Add/update tags for a single memory (called on remember_this)."""
        if not tags_str:
            return
        with self._lock:
            self.conn.execute("DELETE FROM tags WHERE memory_id = ?", (memory_id,))
            rows = [(memory_id, t.strip()) for t in tags_str.split(",") if t.strip()]
            self.conn.executemany("INSERT INTO tags VALUES (?, ?)", rows)
            # Increment sync count
            row = self.conn.execute(
                "SELECT value FROM sync_meta WHERE key='sync_count'"
            ).fetchone()
            if row:
                self._update_sync_count(int(row[0]) + 1)
            else:
                self.conn.commit()

    def remove(self, memory_id):
        """Remove tags for a memory (used by dedup sweep)."""
        with self._lock:
            self.conn.execute("DELETE FROM tags WHERE memory_id = ?", (memory_id,))
            self.conn.commit()

    def tag_search(self, tags_list, match_all=False, top_k=15):
        """Boolean tag search. Returns list of memory_id strings."""
        if not tags_list:
            return []
        placeholders = ",".join("?" * len(tags_list))
        with self._lock:
            if match_all:
                sql = f"""SELECT memory_id FROM tags
                    WHERE tag IN ({placeholders})
                    GROUP BY memory_id HAVING COUNT(DISTINCT tag) = ?
                    LIMIT ?"""
                rows = self.conn.execute(
                    sql, (*tags_list, len(tags_list), top_k)
                ).fetchall()
            else:
                sql = f"""SELECT DISTINCT memory_id FROM tags
                    WHERE tag IN ({placeholders})
                    LIMIT ?"""
                rows = self.conn.execute(sql, (*tags_list, top_k)).fetchall()
        return [r[0] for r in rows]
