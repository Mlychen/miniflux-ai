from pathlib import Path
import threading

from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_saved_entries_repository_sqlite"


class TestSavedEntriesRepositorySQLite:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_upsert_inserts_then_updates_duplicate(self):
        repo = SavedEntriesRepositorySQLite(
            path=str(TMP_DIR / "saved_entries.db"), lock=threading.Lock()
        )
        entry = {"id": 1, "title": "AI News Daily", "url": "https://example.com/a"}
        created = repo.upsert_saved_entry(
            canonical_id="canon-1", entry=entry, feed={"title": "Feed"}, now_ts=1000
        )
        assert created is True

        created_again = repo.upsert_saved_entry(
            canonical_id="canon-1",
            entry={"id": 1, "title": "AI News Daily", "url": "https://example.com/a"},
            feed={"title": "Feed"},
            now_ts=2000,
        )
        assert created_again is False

        rows = repo.search_by_title("ai", mode="prefix", limit=10, offset=0)
        assert len(rows) == 1
        assert rows[0]["save_count"] == 2
        assert rows[0]["first_saved_at"] == 1000
        assert rows[0]["last_saved_at"] == 2000

    def test_search_by_title_supports_prefix_contains_exact(self):
        repo = SavedEntriesRepositorySQLite(
            path=str(TMP_DIR / "saved_entries_search.db"), lock=threading.Lock()
        )
        repo.upsert_saved_entry(
            canonical_id="canon-1",
            entry={"id": 1, "title": "AI Agents Weekly", "url": "https://example.com/1"},
            feed={"title": "Feed"},
            now_ts=1000,
        )
        repo.upsert_saved_entry(
            canonical_id="canon-2",
            entry={
                "id": 2,
                "title": "Database Performance Notes",
                "url": "https://example.com/2",
            },
            feed={"title": "Feed"},
            now_ts=1001,
        )

        prefix_rows = repo.search_by_title("ai", mode="prefix", limit=10, offset=0)
        contains_rows = repo.search_by_title("performance", mode="contains", limit=10, offset=0)
        exact_rows = repo.search_by_title("ai agents weekly", mode="exact", limit=10, offset=0)

        assert len(prefix_rows) == 1
        assert prefix_rows[0]["canonical_id"] == "canon-1"
        assert len(contains_rows) == 1
        assert contains_rows[0]["canonical_id"] == "canon-2"
        assert len(exact_rows) == 1
        assert exact_rows[0]["canonical_id"] == "canon-1"
