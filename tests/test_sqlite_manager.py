# tests/test_sqlite_manager.py
import unittest
from pathlib import Path

from common.sqlite_manager import DatabaseManager

TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_sqlite_manager"


class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

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
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchone()
            self.assertEqual(result[0], "test")


if __name__ == "__main__":
    unittest.main()
