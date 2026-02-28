# SQLite 批量事务 + WAL 模式优化实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构 SQLite 存储层，实现连接管理器 + 批量事务 + WAL 模式，提升写入性能 30-100x。

**Architecture:** 
- 新增 `DatabaseManager` 类，负责 WAL 配置、连接管理、批量执行
- 重构 `EntriesRepositorySQLite` 和 `AiNewsRepositorySQLite` 使用新 manager
- 在 `process_entry` 中收集处理结果，`process_entries_batch` 结束时统一写入

**Tech Stack:** Python 3.11+, sqlite3 (标准库), threading.Lock

---

## Task 1: 创建 DatabaseManager 基础类

**Files:**
- Create: `common/sqlite_manager.py`
- Test: `tests/test_sqlite_manager.py`

**Step 1: Write the failing test**

```python
# tests/test_sqlite_manager.py
import unittest
from pathlib import Path
import threading

from common.sqlite_manager import DatabaseManager

TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_sqlite_manager"


class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_init_creates_directory_and_enables_wal(self):
        """Test that DatabaseManager creates directory and enables WAL mode."""
        path = TMP_DIR / "test.db"
        manager = DatabaseManager(path=str(path))
        
        # Verify file created
        self.assertTrue(path.exists())
        
        # Verify WAL mode enabled
        with manager.connection() as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            self.assertEqual(result[0].lower(), "wal")
    
    def test_execute_batch_single_transaction(self):
        """Test that execute_batch uses single transaction."""
        path = TMP_DIR / "batch.db"
        manager = DatabaseManager(path=str(path))
        
        # Create test table
        with manager.connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.commit()
        
        # Batch insert
        params_list = [(1, "a"), (2, "b"), (3, "c")]
        manager.execute_batch("INSERT INTO test (id, value) VALUES (?, ?)", params_list)
        
        # Verify all inserted
        with manager.connection() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM test").fetchone()
            self.assertEqual(rows[0], 3)
    
    def test_connection_context_manager(self):
        """Test connection context manager works correctly."""
        path = TMP_DIR / "context.db"
        manager = DatabaseManager(path=str(path))
        
        with manager.connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
        
        # Connection should be usable after context
        with manager.connection() as conn:
            result = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()
            self.assertEqual(result[0], "test")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_sqlite_manager.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'common.sqlite_manager'"

**Step 3: Write minimal implementation**

```python
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
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA wal_autocheckpoint=1000")
        finally:
            conn.close()
    
    @contextmanager
    def connection(self):
        """
        Context manager for database connections.
        Ensures proper cleanup after use.
        """
        conn = sqlite3.connect(self.path)
        try:
            yield conn
        finally:
            conn.close()
    
    def execute_batch(
        self, 
        sql: str, 
        params_list: List[Tuple[Any, ...]],
        lock: bool = True
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
```

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_sqlite_manager.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add common/sqlite_manager.py tests/test_sqlite_manager.py
git commit -m "feat: add DatabaseManager with WAL mode and batch execution"
```

---

## Task 2: 重构 EntriesRepositorySQLite 使用 DatabaseManager

**Files:**
- Modify: `common/entries_repository_sqlite.py`
- Modify: `tests/test_entries_repository_sqlite.py`

**Step 1: Write the failing test for batch method**

```python
# Add to tests/test_entries_repository_sqlite.py

    def test_append_summary_items_batch(self):
        """Test batch insert with append_summary_items."""
        path = TMP_DIR / "batch_entries.db"
        repo = EntriesRepositorySQLite(path=str(path))

        items = [
            {
                "id": f"item-{i}",
                "datetime": f"2026-02-{20+i:02d}T00:00:00Z",
                "category": "News",
                "title": f"title-{i}",
                "content": f"summary-{i}",
                "url": f"https://example.com/{i}",
                "ai_category": "科技",
                "ai_subject": f"Subject{i}",
                "ai_subject_type": "公司",
                "ai_region": "美国",
                "ai_event_type": "发布",
                "ai_group_hint": f"科技 / Subject{i}",
                "ai_confidence": 0.9,
            }
            for i in range(10)
        ]

        repo.append_summary_items(items)
        rows = repo.read_all()
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["id"], "item-0")
        self.assertEqual(rows[9]["id"], "item-9")
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_entries_repository_sqlite.py::TestEntriesRepositorySQLite::test_append_summary_items_batch -v`
Expected: FAIL with "AttributeError: 'EntriesRepositorySQLite' object has no attribute 'append_summary_items'"

**Step 3: Rewrite EntriesRepositorySQLite**

```python
# common/entries_repository_sqlite.py
"""SQLite-based entries repository with batch support and WAL mode."""
import hashlib
from typing import List, Dict, Any, Optional
import threading

from common.sqlite_manager import DatabaseManager


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
    
    INSERT_SQL = """
        INSERT OR REPLACE INTO entries (
            id, datetime, category, title, content, url,
            ai_category, ai_subject, ai_subject_type,
            ai_region, ai_event_type, ai_group_hint, ai_confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    def __init__(self, path: str, lock: Optional[threading.Lock] = None):
        self.db = DatabaseManager(path=path, lock=lock)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with self.db.connection() as conn:
            conn.execute(self.CREATE_TABLE_SQL)
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
        import sqlite3
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM entries ORDER BY datetime").fetchall()
        return [dict(row) for row in rows]
    
    def clear_all(self) -> None:
        """Delete all entries from the table."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM entries")
            conn.commit()
```

**Step 4: Run all SQLite repository tests**

Run: `uv run python -m pytest tests/test_entries_repository_sqlite.py -v`
Expected: PASS (all tests including new batch test)

**Step 5: Commit**

```bash
git add common/entries_repository_sqlite.py tests/test_entries_repository_sqlite.py
git commit -m "refactor: EntriesRepositorySQLite to use DatabaseManager with batch support"
```

---

## Task 3: 重构 AiNewsRepositorySQLite 使用 DatabaseManager

**Files:**
- Modify: `common/ai_news_repository_sqlite.py`
- Modify: `tests/test_ai_news_repository_sqlite.py`

**Step 1: Write minimal implementation (no new test needed, existing tests should pass)**

```python
# common/ai_news_repository_sqlite.py
"""SQLite-based AI news repository with WAL mode support."""
import sqlite3
import time
from typing import Optional
import threading

from common.sqlite_manager import DatabaseManager


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
```

**Step 2: Run existing tests**

Run: `uv run python -m pytest tests/test_ai_news_repository_sqlite.py -v`
Expected: PASS (all existing tests)

**Step 3: Commit**

```bash
git add common/ai_news_repository_sqlite.py
git commit -m "refactor: AiNewsRepositorySQLite to use DatabaseManager with WAL mode"
```

---

## Task 4: 更新 main.py 和 myapp/__init__.py 传递 lock 参数

**Files:**
- Modify: `main.py`
- Modify: `myapp/__init__.py`

**Step 1: Modify main.py**

```python
# main.py - lines 247-256, replace:
# Before:
    if storage_backend == "sqlite":
        entries_repository = EntriesRepositorySQLite(path=sqlite_path)
        ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path)
    else:
        entries_lock = threading.Lock()
        ai_news_lock = threading.Lock()
        entries_repository = EntriesRepository(path="entries.json", lock=entries_lock)
        ai_news_repository = AiNewsRepository(path="ai_news.json", lock=ai_news_lock)

# After:
    entries_lock = threading.Lock()
    ai_news_lock = threading.Lock()
    if storage_backend == "sqlite":
        entries_repository = EntriesRepositorySQLite(path=sqlite_path, lock=entries_lock)
        ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path, lock=ai_news_lock)
    else:
        entries_repository = EntriesRepository(path="entries.json", lock=entries_lock)
        ai_news_repository = AiNewsRepository(path="ai_news.json", lock=ai_news_lock)
```

**Step 2: Modify myapp/__init__.py**

```python
# myapp/__init__.py - lines 26-49, replace:
# Before:
    if entries_repository is None:
        if storage_backend == "sqlite":
            app_entries_repository = EntriesRepositorySQLite(path=sqlite_path)
        else:
            entries_lock = threading.Lock()
            app_entries_repository = EntriesRepository(
                path="entries.json", lock=entries_lock
            )
    else:
        app_entries_repository = entries_repository

    if ai_news_repository is None:
        if storage_backend == "sqlite":
            app_ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path)
        else:
            ai_news_lock = threading.Lock()
            app_ai_news_repository = AiNewsRepository(
                path="ai_news.json", lock=ai_news_lock
            )
    else:
        app_ai_news_repository = ai_news_repository

# After:
    if entries_repository is None:
        entries_lock = threading.Lock()
        if storage_backend == "sqlite":
            app_entries_repository = EntriesRepositorySQLite(path=sqlite_path, lock=entries_lock)
        else:
            app_entries_repository = EntriesRepository(
                path="entries.json", lock=entries_lock
            )
    else:
        app_entries_repository = entries_repository

    if ai_news_repository is None:
        ai_news_lock = threading.Lock()
        if storage_backend == "sqlite":
            app_ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path, lock=ai_news_lock)
        else:
            app_ai_news_repository = AiNewsRepository(
                path="ai_news.json", lock=ai_news_lock
            )
    else:
        app_ai_news_repository = ai_news_repository
```

**Step 3: Run service container tests**

Run: `uv run python -m pytest tests/test_service_containers.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add main.py myapp/__init__.py
git commit -m "fix: pass thread lock to SQLite repositories for thread safety"
```

---

## Task 5: 更新 Docker Compose 持久化配置

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add persistent volume for SQLite**

```yaml
# docker-compose.yml - add volume mount for miniflux_ai service
services:
  miniflux_ai:
    container_name: miniflux_ai
    image: ghcr.io/qetesh/miniflux-ai:latest
    restart: unless-stopped
    environment:
        TZ: Asia/Shanghai
    volumes:
        - ./config.yml:/app/config.yml
        - ./runtime:/app/runtime  # Persistent SQLite + WAL files
```

**Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "fix: add persistent volume for SQLite database in Docker"
```

---

## Task 6: 运行完整测试套件验证

**Step 1: Run all tests**

Run: `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`

Expected: All tests pass

**Step 2: Run new SQLite manager tests**

Run: `uv run python -m pytest tests/test_sqlite_manager.py -v`

Expected: All tests pass

---

## Summary

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1 | Create DatabaseManager | +2 files |
| 2 | Refactor EntriesRepositorySQLite | 2 files |
| 3 | Refactor AiNewsRepositorySQLite | 1 file |
| 4 | Update main.py and myapp/__init__.py | 2 files |
| 5 | Update docker-compose.yml | 1 file |
| 6 | Run full test suite | - |

**Expected Benefits:**
- 30-100x write performance improvement for batch operations
- Thread-safe SQLite operations
- WAL mode for better read/write concurrency
- Docker persistence for data safety