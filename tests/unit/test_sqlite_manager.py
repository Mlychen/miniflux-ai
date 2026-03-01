# tests/test_sqlite_manager.py
from pathlib import Path

from common.sqlite_manager import DatabaseManager

TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_sqlite_manager"


class TestDatabaseManager:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_init_creates_directory_and_enables_wal(self):
        path = TMP_DIR / "test.db"
        manager = DatabaseManager(path=str(path))

        assert path.exists()

        with manager.connection() as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0].lower() == "wal"

    def test_execute_batch_single_transaction(self):
        path = TMP_DIR / "batch.db"
        manager = DatabaseManager(path=str(path))

        with manager.connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.commit()

        params_list = [(1, "a"), (2, "b"), (3, "c")]
        manager.execute_batch("INSERT INTO test (id, value) VALUES (?, ?)", params_list)

        with manager.connection() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM test").fetchone()
            assert rows[0] == 3

    def test_connection_context_manager(self):
        path = TMP_DIR / "context.db"
        manager = DatabaseManager(path=str(path))

        with manager.connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()

        with manager.connection() as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchone()
            assert result[0] == "test"
