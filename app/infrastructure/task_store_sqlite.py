import json
import sqlite3
import time
import threading
from typing import Any, Dict, List, Optional

from app.infrastructure.sqlite_manager import DatabaseManager
from app.domain.task_error_key import normalize_error_key
from app.domain.task_store import (
    TASK_DEAD,
    TASK_DONE,
    TASK_PENDING,
    TASK_RETRYABLE,
    TASK_RUNNING,
    TASK_STATUSES,
    TaskRecord,
)


class TaskStoreSQLite:
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            trace_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'retryable', 'dead', 'done')),
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            next_retry_at INTEGER,
            leased_until INTEGER,
            last_error TEXT,
            error_key TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """

    CREATE_INDEX_STATUS_SQL = """
        CREATE INDEX IF NOT EXISTS idx_tasks_status_retry_lease
        ON tasks (status, next_retry_at, leased_until)
    """

    CREATE_INDEX_CREATED_SQL = """
        CREATE INDEX IF NOT EXISTS idx_tasks_created
        ON tasks (created_at, id)
    """

    CREATE_INDEX_STATUS_ERROR_UPDATED_SQL = """
        CREATE INDEX IF NOT EXISTS idx_tasks_status_error_updated
        ON tasks (status, error_key, updated_at)
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()
        self._new_task_cond = threading.Condition()

    def wait_for_new_task(self, timeout: float = 1.0) -> None:
        """Wait for new task signal or timeout."""
        with self._new_task_cond:
            self._new_task_cond.wait(timeout)

    def _init_db(self) -> None:
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
            conn.row_factory = sqlite3.Row
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "error_key" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN error_key TEXT NOT NULL DEFAULT ''")
            conn.execute(self.CREATE_INDEX_STATUS_SQL)
            conn.execute(self.CREATE_INDEX_CREATED_SQL)
            conn.execute(self.CREATE_INDEX_STATUS_ERROR_UPDATED_SQL)
            conn.commit()

    def _now(self, now_ts: Optional[int]) -> int:
        return int(now_ts if now_ts is not None else time.time())

    def _row_to_task(self, row: sqlite3.Row, include_payload: bool = True) -> TaskRecord:
        payload: Dict[str, Any] = {}
        if include_payload:
            payload_json = row["payload_json"] or "{}"
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
        return TaskRecord(
            id=int(row["id"]),
            canonical_id=str(row["canonical_id"]),
            payload=payload,
            trace_id=str(row["trace_id"] or ""),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            next_retry_at=row["next_retry_at"],
            leased_until=row["leased_until"],
            last_error=row["last_error"],
            error_key=str(row["error_key"] or ""),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def create_task(
        self,
        canonical_id: str,
        payload: Dict[str, Any],
        trace_id: str = "",
        max_attempts: int = 5,
        now_ts: Optional[int] = None,
    ) -> bool:
        now = self._now(now_ts)
        payload_json = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        attempts_cap = max(1, int(max_attempts))
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    canonical_id,
                    payload_json,
                    trace_id,
                    status,
                    attempts,
                    max_attempts,
                    next_retry_at,
                    leased_until,
                    last_error,
                    error_key,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, NULL, NULL, NULL, '', ?, ?)
                """,
                (canonical_id, payload_json, trace_id, TASK_PENDING, attempts_cap, now, now),
            )
            conn.commit()
            if cur.rowcount > 0:
                with self._new_task_cond:
                    self._new_task_cond.notify_all()
            return cur.rowcount > 0

    def claim_tasks(
        self,
        limit: int,
        lease_seconds: int = 30,
        now_ts: Optional[int] = None,
    ) -> List[TaskRecord]:
        batch_size = max(0, int(limit))
        if batch_size <= 0:
            return []

        now = self._now(now_ts)
        lease_until = now + max(1, int(lease_seconds))

        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id
                FROM tasks
                WHERE
                    status = ?
                    OR (status = ? AND COALESCE(next_retry_at, 0) <= ?)
                    OR (status = ? AND COALESCE(leased_until, 0) <= ?)
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (
                    TASK_PENDING,
                    TASK_RETRYABLE,
                    now,
                    TASK_RUNNING,
                    now,
                    batch_size,
                ),
            ).fetchall()
            if not rows:
                conn.commit()
                return []

            task_ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in task_ids)
            conn.execute(
                f"""
                UPDATE tasks
                SET
                    status = ?,
                    attempts = attempts + 1,
                    leased_until = ?,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [TASK_RUNNING, lease_until, now, *task_ids],
            )
            claimed_rows = conn.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE id IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                """,
                task_ids,
            ).fetchall()
            conn.commit()
            return [self._row_to_task(row) for row in claimed_rows]

    def mark_done(self, task_id: int, now_ts: Optional[int] = None) -> None:
        now = self._now(now_ts)
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET
                    status = ?,
                    leased_until = NULL,
                    next_retry_at = NULL,
                    last_error = NULL,
                    error_key = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (TASK_DONE, now, int(task_id)),
            )
            conn.commit()

    def mark_retryable(
        self,
        task_id: int,
        error: str,
        retry_delay_seconds: int = 30,
        now_ts: Optional[int] = None,
    ) -> None:
        now = self._now(now_ts)
        retry_at = now + max(0, int(retry_delay_seconds))
        error_text = str(error)
        error_key = normalize_error_key(error_text)
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET
                    status = CASE
                        WHEN attempts >= max_attempts THEN ?
                        ELSE ?
                    END,
                    next_retry_at = CASE
                        WHEN attempts >= max_attempts THEN NULL
                        ELSE ?
                    END,
                    leased_until = NULL,
                    last_error = ?,
                    error_key = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (TASK_DEAD, TASK_RETRYABLE, retry_at, error_text, error_key, now, int(task_id)),
            )
            conn.commit()

    def mark_dead(self, task_id: int, error: str, now_ts: Optional[int] = None) -> None:
        now = self._now(now_ts)
        error_text = str(error)
        error_key = normalize_error_key(error_text)
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET
                    status = ?,
                    leased_until = NULL,
                    next_retry_at = NULL,
                    last_error = ?,
                    error_key = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (TASK_DEAD, error_text, error_key, now, int(task_id)),
            )
            conn.commit()

    def get_task(self, task_id: int) -> Optional[TaskRecord]:
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def get_task_by_canonical_id(self, canonical_id: str) -> Optional[TaskRecord]:
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE canonical_id = ?", (canonical_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def list_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_payload: bool = True,
    ) -> List[TaskRecord]:
        row_limit = max(1, int(limit))
        row_offset = max(0, int(offset))
        if include_payload:
            columns = "*"
        else:
            columns = """
                id,
                canonical_id,
                '' AS payload_json,
                trace_id,
                status,
                attempts,
                max_attempts,
                next_retry_at,
                leased_until,
                last_error,
                error_key,
                created_at,
                updated_at
            """
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    f"""
                    SELECT {columns}
                    FROM tasks
                    WHERE status = ?
                    ORDER BY created_at ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (status, row_limit, row_offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT {columns}
                    FROM tasks
                    ORDER BY created_at ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (row_limit, row_offset),
                ).fetchall()
        return [self._row_to_task(row, include_payload=include_payload) for row in rows]

    def count_tasks(self, status: Optional[str] = None) -> int:
        with self.db.connection() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        return int((row or [0])[0] or 0)

    def count_tasks_by_status(self) -> Dict[str, int]:
        counts = {key: 0 for key in TASK_STATUSES}
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM tasks
                GROUP BY status
                """
            ).fetchall()
        for row in rows:
            status = str(row[0])
            if status in counts:
                counts[status] = int(row[1] or 0)
        return counts

    def get_metrics(
        self,
        now_ts: Optional[int] = None,
        throughput_window_seconds: int = 300,
    ) -> Dict[str, Any]:
        now = self._now(now_ts)
        window_seconds = max(60, int(throughput_window_seconds))
        window_start = now - window_seconds

        with self.db.connection() as conn:
            totals_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count,
                    COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running_count,
                    COALESCE(SUM(CASE WHEN status = 'retryable' THEN 1 ELSE 0 END), 0) AS retryable_count,
                    COALESCE(SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END), 0) AS dead_count,
                    COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0) AS done_count,
                    COUNT(*) AS total_count,
                    COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END), 0) AS retries_total_estimated,
                    COALESCE(SUM(CASE WHEN status IN ('done', 'dead') THEN 1 ELSE 0 END), 0) AS terminal_total,
                    COALESCE(SUM(CASE WHEN status = 'done' THEN attempts ELSE 0 END), 0) AS done_attempts_total,
                    COALESCE(SUM(CASE WHEN status = 'dead' THEN attempts ELSE 0 END), 0) AS dead_attempts_total,
                    COALESCE(SUM(CASE WHEN status = 'done' AND updated_at >= ? THEN 1 ELSE 0 END), 0) AS done_window,
                    COALESCE(SUM(CASE WHEN status = 'dead' AND updated_at >= ? THEN 1 ELSE 0 END), 0) AS dead_window,
                    MIN(CASE WHEN status IN ('pending', 'running', 'retryable') THEN created_at ELSE NULL END) AS oldest_backlog_created_at
                FROM tasks
                """,
                (window_start, window_start),
            ).fetchone()
            ready_to_claim_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM tasks
                WHERE
                    status = ?
                    OR (status = ? AND COALESCE(next_retry_at, 0) <= ?)
                    OR (status = ? AND COALESCE(leased_until, 0) <= ?)
                """,
                (
                    TASK_PENDING,
                    TASK_RETRYABLE,
                    now,
                    TASK_RUNNING,
                    now,
                ),
            ).fetchone()
            delayed_retry_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM tasks
                WHERE status = ? AND COALESCE(next_retry_at, 0) > ?
                """,
                (TASK_RETRYABLE, now),
            ).fetchone()

        pending = int((totals_row or [0])[0] or 0)
        running = int((totals_row or [0] * 13)[1] or 0)
        retryable = int((totals_row or [0] * 13)[2] or 0)
        dead = int((totals_row or [0] * 13)[3] or 0)
        done = int((totals_row or [0] * 13)[4] or 0)
        total = int((totals_row or [0] * 13)[5] or 0)
        retries_total_estimated = int((totals_row or [0] * 13)[6] or 0)
        terminal_total = int((totals_row or [0] * 13)[7] or 0)
        done_attempts_total = int((totals_row or [0] * 13)[8] or 0)
        dead_attempts_total = int((totals_row or [0] * 13)[9] or 0)
        done_window = int((totals_row or [0] * 13)[10] or 0)
        dead_window = int((totals_row or [0] * 13)[11] or 0)
        oldest_backlog_created_at = (totals_row or [None] * 13)[12]

        backlog = pending + running + retryable
        window_minutes = window_seconds / 60.0
        throughput_done_per_minute = done_window / window_minutes if window_minutes > 0 else 0.0
        window_terminal = done_window + dead_window
        terminal_failure_rate = (dead / terminal_total) if terminal_total > 0 else 0.0
        terminal_failure_rate_window = (
            dead_window / window_terminal if window_terminal > 0 else 0.0
        )
        avg_attempts_done = (done_attempts_total / done) if done > 0 else 0.0
        avg_attempts_dead = (dead_attempts_total / dead) if dead > 0 else 0.0
        retries_per_task_estimated = (retries_total_estimated / total) if total > 0 else 0.0
        oldest_backlog_age_seconds = (
            max(0, now - int(oldest_backlog_created_at))
            if oldest_backlog_created_at is not None
            else 0
        )

        ready_to_claim = int((ready_to_claim_row or [0])[0] or 0)
        delayed_retry = int((delayed_retry_row or [0])[0] or 0)

        return {
            "time": {
                "now_ts": now,
                "throughput_window_seconds": window_seconds,
                "throughput_window_start_ts": window_start,
            },
            "counts": {
                "pending": pending,
                "running": running,
                "retryable": retryable,
                "dead": dead,
                "done": done,
                "total": total,
                "backlog": backlog,
                "ready_to_claim": ready_to_claim,
                "delayed_retry": delayed_retry,
            },
            "flow": {
                "done_window": done_window,
                "dead_window": dead_window,
                "throughput_done_per_minute": throughput_done_per_minute,
                "terminal_failure_rate": terminal_failure_rate,
                "terminal_failure_rate_window": terminal_failure_rate_window,
            },
            "retries": {
                "retries_total_estimated": retries_total_estimated,
                "retries_per_task_estimated": retries_per_task_estimated,
                "avg_attempts_done": avg_attempts_done,
                "avg_attempts_dead": avg_attempts_dead,
            },
            "latency": {
                "oldest_backlog_age_seconds": oldest_backlog_age_seconds,
            },
        }

    def _build_failure_where(self, status: Optional[str], error_key: Optional[str] = None):
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        else:
            clauses.append("status IN (?, ?)")
            params.extend([TASK_RETRYABLE, TASK_DEAD])
        if error_key:
            clauses.append(
                """
                CASE
                    WHEN error_key IS NULL OR TRIM(error_key) = '' THEN '(empty)'
                    ELSE error_key
                END = ?
                """
            )
            params.append(error_key)
        return " AND ".join(clauses), params

    def count_failure_groups(
        self, status: Optional[str] = None, error_key: Optional[str] = None
    ) -> int:
        where_clause, params = self._build_failure_where(status, error_key=error_key)
        with self.db.connection() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT 1
                    FROM tasks
                    WHERE {where_clause}
                    GROUP BY
                        status,
                        CASE
                            WHEN error_key IS NULL OR TRIM(error_key) = '' THEN '(empty)'
                            ELSE error_key
                        END
                ) grouped_failures
                """,
                params,
            ).fetchone()
        return int((row or [0])[0] or 0)

    def count_failed_tasks(
        self, status: Optional[str] = None, error_key: Optional[str] = None
    ) -> int:
        where_clause, params = self._build_failure_where(status, error_key=error_key)
        with self.db.connection() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM tasks
                WHERE {where_clause}
                """,
                params,
            ).fetchone()
        return int((row or [0])[0] or 0)

    def list_failure_groups(
        self,
        status: Optional[str] = None,
        error_key: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        row_limit = max(1, int(limit))
        row_offset = max(0, int(offset))
        where_clause, params = self._build_failure_where(status, error_key=error_key)

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    status,
                    CASE
                        WHEN error_key IS NULL OR TRIM(error_key) = '' THEN '(empty)'
                        ELSE error_key
                    END AS error_key,
                    MAX(
                        CASE
                            WHEN last_error IS NULL OR TRIM(last_error) = '' THEN '(empty)'
                            ELSE last_error
                        END
                    ) AS example_error,
                    COUNT(*) AS count,
                    MAX(updated_at) AS latest_updated_at,
                    MIN(created_at) AS oldest_created_at
                FROM tasks
                WHERE {where_clause}
                GROUP BY
                    status,
                    CASE
                        WHEN error_key IS NULL OR TRIM(error_key) = '' THEN '(empty)'
                        ELSE error_key
                    END
                ORDER BY count DESC, latest_updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, row_limit, row_offset],
            ).fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "status": str(row[0]),
                    "error_key": str(row[1]),
                    "error": str(row[2]),
                    "count": int(row[3] or 0),
                    "latest_updated_at": int(row[4] or 0),
                    "oldest_created_at": int(row[5] or 0),
                }
            )
        return result

    def list_failed_tasks(
        self,
        status: Optional[str] = None,
        error_key: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_payload: bool = False,
    ) -> List[TaskRecord]:
        row_limit = max(1, int(limit))
        row_offset = max(0, int(offset))
        where_clause, params = self._build_failure_where(status, error_key=error_key)

        if include_payload:
            columns = "*"
        else:
            columns = """
                id,
                canonical_id,
                '' AS payload_json,
                trace_id,
                status,
                attempts,
                max_attempts,
                next_retry_at,
                leased_until,
                last_error,
                error_key,
                created_at,
                updated_at
            """

        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT {columns}
                FROM tasks
                WHERE {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, row_limit, row_offset],
            ).fetchall()
        return [self._row_to_task(row, include_payload=include_payload) for row in rows]

    def requeue_task(self, task_id: int, now_ts: Optional[int] = None) -> bool:
        now = self._now(now_ts)
        with self.db.connection() as conn:
            cur = conn.execute(
                """
                UPDATE tasks
                SET
                    status = ?,
                    next_retry_at = NULL,
                    leased_until = NULL,
                    last_error = NULL,
                    error_key = '',
                    updated_at = ?
                WHERE
                    id = ?
                    AND status IN (?, ?, ?)
                """,
                (TASK_PENDING, now, int(task_id), TASK_DEAD, TASK_RETRYABLE, TASK_RUNNING),
            )
            conn.commit()
            if cur.rowcount > 0:
                with self._new_task_cond:
                    self._new_task_cond.notify_all()
            return cur.rowcount > 0

    def requeue_tasks(
        self,
        status: Optional[str] = TASK_DEAD,
        limit: int = 100,
        error_key: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> int:
        now = self._now(now_ts)
        row_limit = max(1, int(limit))
        where_clauses: List[str] = []
        params: List[Any] = []

        if status:
            where_clauses.append("status = ?")
            params.append(status)
        else:
            where_clauses.append("status IN (?, ?)")
            params.extend([TASK_RETRYABLE, TASK_DEAD])

        if error_key is not None:
            where_clauses.append(
                """
                CASE
                    WHEN error_key IS NULL OR TRIM(error_key) = '' THEN '(empty)'
                    ELSE error_key
                END = ?
                """
            )
            params.append(str(error_key))

        where_sql = " AND ".join(where_clauses)
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT id
                FROM tasks
                WHERE {where_sql}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                [*params, row_limit],
            ).fetchall()
            if not rows:
                conn.commit()
                return 0

            task_ids = [int(row["id"]) for row in rows]
            placeholders = ",".join("?" for _ in task_ids)
            conn.execute(
                f"""
                UPDATE tasks
                SET
                    status = ?,
                    next_retry_at = NULL,
                    leased_until = NULL,
                    last_error = NULL,
                    error_key = '',
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [TASK_PENDING, now, *task_ids],
            )
            conn.commit()
            if task_ids:
                with self._new_task_cond:
                    self._new_task_cond.notify_all()
            return len(task_ids)
