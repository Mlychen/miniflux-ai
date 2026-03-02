# common/sqlite_manager.py
"""SQLite connection manager with WAL mode and batch execution support."""

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import List, Tuple, Any, Optional


class DatabaseManager:
    """
    Manages SQLite connections with WAL mode, thread-local storage,
    and batch execution support.
    """

    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.path = path
        self._lock = lock or threading.Lock()
        self._local = threading.local()
        self._ensure_dir()
        self._enable_wal()

    def _ensure_dir(self):
        """Create parent directory if it doesn't exist."""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _enable_wal(self):
        """Enable WAL mode and configure PRAGMA settings."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.execute("PRAGMA busy_timeout=5000")

    def _get_connection(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            return existing
        conn = sqlite3.connect(self.path)
        self._configure_connection(conn)
        self._local.conn = conn
        return conn

    @contextmanager
    def connection(self):
        """
        Context manager for database connections.
        Ensures proper cleanup after use.
        """
        conn = self._get_connection()
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.close_thread_connection()

    def close_thread_connection(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        try:
            conn.close()
        finally:
            self._local.conn = None

    def execute_batch(
        self, sql: str, params_list: List[Tuple[Any, ...]], lock: bool = True
    ) -> int:
        """
        Execute a SQL statement multiple times with different parameters
        in a single transaction.

        Args:
            sql: SQL statement with placeholders
            params_list: List of parameter tuples
            lock: Whether to use thread lock (default True)

        Returns:
            Number of rows affected
        """
        if not params_list:
            return 0

        def _execute():
            with self.connection() as conn:
                conn.executemany(sql, params_list)
                conn.commit()
            return len(params_list)

        if lock:
            with self._lock:
                return _execute()
        return _execute()
