"""SQLite-based AI news repository with WAL mode support."""

import time
from typing import Optional
import threading

from app.infrastructure.sqlite_manager import DatabaseManager


class AiNewsRepositorySQLite:
    """
    Repository for storing and retrieving AI-generated news in SQLite.
    """

    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS ai_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            content TEXT
        )
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.commit()

    def save_latest(self, content: str) -> None:
        """
        Save the latest AI news content.
        Deletes any existing content first.
        """
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.db.connection() as conn:
            conn.execute("DELETE FROM ai_news")
            conn.execute(
                "INSERT INTO ai_news (created_at, content) VALUES (?, ?)",
                (created_at, content),
            )
            conn.commit()

    def consume_latest(self) -> str:
        """
        Retrieve and delete the latest AI news content.

        Returns:
            The content string, or empty string if none exists.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT content FROM ai_news ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.execute("DELETE FROM ai_news")
            conn.commit()
        if not row:
            return ""
        return row[0] if row[0] is not None else ""
