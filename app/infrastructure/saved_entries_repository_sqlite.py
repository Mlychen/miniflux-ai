import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.infrastructure.sqlite_manager import DatabaseManager


class SavedEntriesRepositorySQLite:
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS saved_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL UNIQUE,
            entry_id INTEGER,
            title TEXT NOT NULL,
            title_norm TEXT NOT NULL,
            url TEXT,
            feed_title TEXT,
            content TEXT,
            first_saved_at INTEGER NOT NULL,
            last_saved_at INTEGER NOT NULL,
            save_count INTEGER NOT NULL DEFAULT 1
        )
    """

    CREATE_INDEX_TITLE_NORM_SQL = """
        CREATE INDEX IF NOT EXISTS idx_saved_entries_title_norm
        ON saved_entries(title_norm)
    """

    CREATE_INDEX_LAST_SAVED_SQL = """
        CREATE INDEX IF NOT EXISTS idx_saved_entries_last_saved_at
        ON saved_entries(last_saved_at DESC)
    """

    INSERT_SQL = """
        INSERT OR IGNORE INTO saved_entries (
            canonical_id,
            entry_id,
            title,
            title_norm,
            url,
            feed_title,
            content,
            first_saved_at,
            last_saved_at,
            save_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """

    UPDATE_DUPLICATE_SQL = """
        UPDATE saved_entries
        SET
            last_saved_at = ?,
            save_count = save_count + 1,
            entry_id = COALESCE(?, entry_id),
            title = ?,
            title_norm = ?,
            url = COALESCE(?, url),
            feed_title = COALESCE(?, feed_title),
            content = COALESCE(?, content)
        WHERE canonical_id = ?
    """

    LIST_MISSING_FEED_TITLE_SQL = """
        SELECT id, canonical_id, entry_id
        FROM saved_entries
        WHERE feed_title IS NULL OR TRIM(feed_title) = ''
        ORDER BY id ASC
        LIMIT ?
    """

    UPDATE_FEED_TITLE_SQL = """
        UPDATE saved_entries
        SET feed_title = ?
        WHERE id = ?
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()

    def _init_db(self) -> None:
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.execute(self.CREATE_INDEX_TITLE_NORM_SQL)
            conn.execute(self.CREATE_INDEX_LAST_SAVED_SQL)
            conn.commit()

    def _now(self, now_ts: Optional[int]) -> int:
        return int(now_ts if now_ts is not None else time.time())

    def _normalize_title(self, title: str) -> str:
        return re.sub(r"\s+", " ", str(title or "").strip().lower())

    def _to_optional_int(self, value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                return int(text)
        return None

    def _to_row_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "canonical_id": str(row["canonical_id"]),
            "entry_id": row["entry_id"],
            "title": str(row["title"]),
            "title_norm": str(row["title_norm"]),
            "url": row["url"],
            "feed_title": row["feed_title"],
            "content": row["content"],
            "first_saved_at": int(row["first_saved_at"]),
            "last_saved_at": int(row["last_saved_at"]),
            "save_count": int(row["save_count"]),
        }

    def upsert_saved_entry(
        self,
        canonical_id: str,
        entry: Dict[str, Any],
        feed: Optional[Dict[str, Any]] = None,
        now_ts: Optional[int] = None,
    ) -> bool:
        title = str((entry or {}).get("title") or "").strip()
        if not title:
            raise ValueError("entry title is required")
        now = self._now(now_ts)
        title_norm = self._normalize_title(title)
        entry_id_raw = (entry or {}).get("id")
        entry_id = self._to_optional_int(entry_id_raw)
        url = (entry or {}).get("url")
        content = (entry or {}).get("content")
        feed_title = ""
        if isinstance(feed, dict):
            feed_title = str(
                (feed.get("title") or (feed.get("category") or {}).get("title") or "")
            ).strip()

        with self.db.connection() as conn:
            cursor = conn.execute(
                self.INSERT_SQL,
                (
                    canonical_id,
                    entry_id,
                    title,
                    title_norm,
                    url,
                    feed_title or None,
                    content,
                    now,
                    now,
                ),
            )
            created = cursor.rowcount > 0
            if not created:
                conn.execute(
                    self.UPDATE_DUPLICATE_SQL,
                    (
                        now,
                        entry_id,
                        title,
                        title_norm,
                        url,
                        feed_title or None,
                        content,
                        canonical_id,
                    ),
                )
            conn.commit()
            return created

    def _build_title_filter(self, title: str, mode: str) -> Tuple[str, List[Any]]:
        norm = self._normalize_title(title)
        if not norm:
            return "1=1", []
        if mode == "contains":
            return "title_norm LIKE ?", [f"%{norm}%"]
        if mode == "exact":
            return "title_norm = ?", [norm]
        return "title_norm LIKE ?", [f"{norm}%"]

    def search_by_title(
        self,
        title: str,
        mode: str = "prefix",
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        row_limit = max(1, min(int(limit), 500))
        row_offset = max(0, int(offset))
        where_sql, params = self._build_title_filter(title, mode)
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM saved_entries
                WHERE {where_sql}
                ORDER BY last_saved_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, row_limit, row_offset],
            ).fetchall()
        return [self._to_row_dict(row) for row in rows]

    def count_by_title(self, title: str, mode: str = "prefix") -> int:
        where_sql, params = self._build_title_filter(title, mode)
        with self.db.connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM saved_entries WHERE {where_sql}",
                params,
            ).fetchone()
        return int((row or [0])[0] or 0)

    def list_missing_feed_title(self, limit: int = 200) -> List[Dict[str, Any]]:
        row_limit = max(1, min(int(limit), 2000))
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(self.LIST_MISSING_FEED_TITLE_SQL, (row_limit,)).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "id": int(row["id"]),
                    "canonical_id": str(row["canonical_id"]),
                    "entry_id": row["entry_id"],
                }
            )
        return result

    def update_feed_title(self, row_id: int, feed_title: str) -> bool:
        title = str(feed_title or "").strip()
        if not title:
            return False
        with self.db.connection() as conn:
            cursor = conn.execute(self.UPDATE_FEED_TITLE_SQL, (title, int(row_id)))
            conn.commit()
            return cursor.rowcount > 0
