import hashlib
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from app.infrastructure.sqlite_manager import DatabaseManager


class SummaryArchiveRepositorySQLite:
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS summary_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            entry_id INTEGER,
            datetime TEXT,
            category TEXT,
            title TEXT NOT NULL,
            url TEXT,
            summary_content TEXT NOT NULL,
            ai_category TEXT,
            ai_subject TEXT,
            ai_subject_type TEXT,
            ai_region TEXT,
            ai_event_type TEXT,
            ai_group_hint TEXT,
            ai_confidence REAL,
            feed_id INTEGER,
            feed_title TEXT,
            processed_at INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            archive_version INTEGER NOT NULL DEFAULT 1
        )
    """

    CREATE_UNIQUE_INDEX_SQL = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_archive_canonical_trace
        ON summary_archive(canonical_id, trace_id)
    """

    CREATE_INDEX_PROCESSED_AT_SQL = """
        CREATE INDEX IF NOT EXISTS idx_summary_archive_processed_at
        ON summary_archive(processed_at DESC)
    """

    CREATE_INDEX_CANONICAL_ID_SQL = """
        CREATE INDEX IF NOT EXISTS idx_summary_archive_canonical_id
        ON summary_archive(canonical_id)
    """

    CREATE_INDEX_FEED_ID_PROCESSED_AT_SQL = """
        CREATE INDEX IF NOT EXISTS idx_summary_archive_feed_id_processed_at
        ON summary_archive(feed_id, processed_at DESC)
    """

    INSERT_SQL = """
        INSERT OR IGNORE INTO summary_archive (
            canonical_id,
            trace_id,
            entry_id,
            datetime,
            category,
            title,
            url,
            summary_content,
            ai_category,
            ai_subject,
            ai_subject_type,
            ai_region,
            ai_event_type,
            ai_group_hint,
            ai_confidence,
            feed_id,
            feed_title,
            processed_at,
            content_hash,
            archive_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    SELECT_BY_CANONICAL_ID_SQL = """
        SELECT *
        FROM summary_archive
        WHERE canonical_id = ?
        ORDER BY processed_at DESC, id DESC
        LIMIT ?
    """

    SELECT_RECENT_SQL = """
        SELECT *
        FROM summary_archive
        ORDER BY processed_at DESC, id DESC
        LIMIT ? OFFSET ?
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()

    def _init_db(self) -> None:
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.execute(self.CREATE_UNIQUE_INDEX_SQL)
            conn.execute(self.CREATE_INDEX_PROCESSED_AT_SQL)
            conn.execute(self.CREATE_INDEX_CANONICAL_ID_SQL)
            conn.execute(self.CREATE_INDEX_FEED_ID_PROCESSED_AT_SQL)
            conn.commit()

    def _now(self, now_ts: Optional[int]) -> int:
        return int(now_ts if now_ts is not None else time.time())

    def _parse_int(self, value: Any) -> Optional[int]:
        text = str(value or "").strip()
        return int(text) if text.isdigit() else None

    def _build_content_hash(
        self,
        title: str,
        url: str,
        summary_content: str,
        ai_category: str,
        ai_subject: str,
        ai_region: str,
        ai_event_type: str,
    ) -> str:
        raw = "\n".join(
            [
                title or "",
                url or "",
                summary_content or "",
                ai_category or "",
                ai_subject or "",
                ai_region or "",
                ai_event_type or "",
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _build_snapshot_params(
        self,
        *,
        canonical_id: str,
        trace_id: str,
        item: Dict[str, Any],
        entry: Optional[Dict[str, Any]] = None,
        feed_id: Optional[int] = None,
        feed_title: Optional[str] = None,
        processed_at: Optional[int] = None,
    ) -> tuple:
        title = str((item or {}).get("title") or "").strip()
        if not title:
            raise ValueError("summary archive title is required")

        summary_content = str((item or {}).get("content") or "").strip()
        if not summary_content:
            raise ValueError("summary archive summary_content is required")

        url = str((item or {}).get("url") or "").strip()
        category = str((item or {}).get("category") or "").strip()
        ai_category = str((item or {}).get("ai_category") or "").strip()
        ai_subject = str((item or {}).get("ai_subject") or "").strip()
        ai_subject_type = str((item or {}).get("ai_subject_type") or "").strip()
        ai_region = str((item or {}).get("ai_region") or "").strip()
        ai_event_type = str((item or {}).get("ai_event_type") or "").strip()
        ai_group_hint = str((item or {}).get("ai_group_hint") or "").strip()
        ai_confidence = (item or {}).get("ai_confidence")
        datetime_text = str((item or {}).get("datetime") or "").strip() or None

        entry_id = None
        if isinstance(entry, dict):
            entry_id = self._parse_int(entry.get("id"))

        content_hash = self._build_content_hash(
            title=title,
            url=url,
            summary_content=summary_content,
            ai_category=ai_category,
            ai_subject=ai_subject,
            ai_region=ai_region,
            ai_event_type=ai_event_type,
        )

        return (
            canonical_id,
            trace_id,
            entry_id,
            datetime_text,
            category or None,
            title,
            url or None,
            summary_content,
            ai_category or None,
            ai_subject or None,
            ai_subject_type or None,
            ai_region or None,
            ai_event_type or None,
            ai_group_hint or None,
            ai_confidence,
            feed_id,
            (feed_title or "").strip() or None,
            self._now(processed_at),
            content_hash,
            1,
        )

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "canonical_id": str(row["canonical_id"]),
            "trace_id": str(row["trace_id"]),
            "entry_id": row["entry_id"],
            "datetime": row["datetime"],
            "category": row["category"],
            "title": str(row["title"]),
            "url": row["url"],
            "summary_content": str(row["summary_content"]),
            "ai_category": row["ai_category"],
            "ai_subject": row["ai_subject"],
            "ai_subject_type": row["ai_subject_type"],
            "ai_region": row["ai_region"],
            "ai_event_type": row["ai_event_type"],
            "ai_group_hint": row["ai_group_hint"],
            "ai_confidence": row["ai_confidence"],
            "feed_id": row["feed_id"],
            "feed_title": row["feed_title"],
            "processed_at": int(row["processed_at"]),
            "content_hash": str(row["content_hash"]),
            "archive_version": int(row["archive_version"]),
        }

    def append_snapshot(
        self,
        *,
        canonical_id: str,
        trace_id: str,
        item: Dict[str, Any],
        entry: Optional[Dict[str, Any]] = None,
        feed_id: Optional[int] = None,
        feed_title: Optional[str] = None,
        processed_at: Optional[int] = None,
    ) -> bool:
        params = self._build_snapshot_params(
            canonical_id=canonical_id,
            trace_id=trace_id,
            item=item,
            entry=entry,
            feed_id=feed_id,
            feed_title=feed_title,
            processed_at=processed_at,
        )
        with self.db.connection() as conn:
            cursor = conn.execute(self.INSERT_SQL, params)
            conn.commit()
            return cursor.rowcount > 0

    def append_snapshots(self, snapshots: List[Dict[str, Any]]) -> int:
        if not snapshots:
            return 0
        created = 0
        with self.db.connection() as conn:
            for snapshot in snapshots:
                cursor = conn.execute(
                    self.INSERT_SQL,
                    self._build_snapshot_params(
                        canonical_id=str(snapshot["canonical_id"]),
                        trace_id=str(snapshot["trace_id"]),
                        item=snapshot["item"],
                        entry=snapshot.get("entry"),
                        feed_id=snapshot.get("feed_id"),
                        feed_title=snapshot.get("feed_title"),
                        processed_at=snapshot.get("processed_at"),
                    ),
                )
                created += max(0, int(cursor.rowcount))
            conn.commit()
        return created

    def get_by_canonical_id(self, canonical_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        row_limit = max(1, min(int(limit), 500))
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                self.SELECT_BY_CANONICAL_ID_SQL,
                (canonical_id, row_limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_recent(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        row_limit = max(1, min(int(limit), 500))
        row_offset = max(0, int(offset))
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                self.SELECT_RECENT_SQL,
                (row_limit, row_offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]
