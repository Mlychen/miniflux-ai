# common/entries_repository_sqlite.py
"""SQLite-based entries repository with batch support and WAL mode."""

import hashlib
import sqlite3
from typing import List, Dict, Any, Optional
import threading

from app.infrastructure.sqlite_manager import DatabaseManager


class EntriesRepositorySQLite:
    """
    Repository for storing and retrieving entry summaries in SQLite.
    Supports both single-item and batch operations.
    """

    # SQL statements
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            datetime TEXT,
            category TEXT,
            title TEXT,
            content TEXT,
            url TEXT,
            ai_category TEXT,
            ai_subject TEXT,
            ai_subject_type TEXT,
            ai_region TEXT,
            ai_event_type TEXT,
            ai_group_hint TEXT,
            ai_confidence REAL
        )
    """

    CREATE_PROCESSED_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS processed_entries (
            canonical_id TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """

    INSERT_SQL = """
        INSERT OR REPLACE INTO entries (
            id, datetime, category, title, content, url,
            ai_category, ai_subject, ai_subject_type,
            ai_region, ai_event_type, ai_group_hint, ai_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    INSERT_PROCESSED_SQL = """
        INSERT OR IGNORE INTO processed_entries (canonical_id) VALUES (?)
    """

    SELECT_PROCESSED_SQL = """
        SELECT 1 FROM processed_entries WHERE canonical_id = ?
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.execute(self.CREATE_PROCESSED_TABLE_SQL)
            conn.commit()

    def _derive_id(self, item: Dict[str, Any]) -> str:
        """Derive a unique ID from item fields."""
        raw = f"{item.get('url')}\n{item.get('title')}\n{item.get('datetime')}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _item_to_tuple(self, item: Dict[str, Any]) -> tuple:
        """Convert item dict to tuple for SQL parameters."""
        entry_id = item.get("id") or self._derive_id(item)
        return (
            entry_id,
            item.get("datetime"),
            item.get("category"),
            item.get("title"),
            item.get("content"),
            item.get("url"),
            item.get("ai_category"),
            item.get("ai_subject"),
            item.get("ai_subject_type"),
            item.get("ai_region"),
            item.get("ai_event_type"),
            item.get("ai_group_hint"),
            item.get("ai_confidence"),
        )

    def append_summary_item(self, item: Dict[str, Any]) -> None:
        """
        Append a single summary item.
        Internally uses batch operation for consistency.
        """
        self.append_summary_items([item])

    def append_summary_items(self, items: List[Dict[str, Any]]) -> None:
        """
        Append multiple summary items in a single transaction.

        Args:
            items: List of item dictionaries to insert
        """
        if not items:
            return
        params_list = [self._item_to_tuple(item) for item in items]
        self.db.execute_batch(self.INSERT_SQL, params_list)

    def read_all(self) -> List[Dict[str, Any]]:
        """Read all entries ordered by datetime."""
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM entries ORDER BY datetime").fetchall()
        return [dict(row) for row in rows]

    def clear_all(self) -> None:
        """Delete all entries from the table."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM entries")
            conn.commit()

    def contains(self, canonical_id: str) -> bool:
        """Check if a canonical_id has already been processed."""
        with self.db.connection() as conn:
            cursor = conn.execute(self.SELECT_PROCESSED_SQL, (canonical_id,))
            return cursor.fetchone() is not None

    def add(self, canonical_id: str):
        """Mark a canonical_id as processed."""
        with self.db.connection() as conn:
            conn.execute(self.INSERT_PROCESSED_SQL, (canonical_id,))
            conn.commit()
