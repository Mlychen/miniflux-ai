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

    def test_list_missing_feed_title_and_update(self):
        repo = SavedEntriesRepositorySQLite(
            path=str(TMP_DIR / "saved_entries_feed_title.db"), lock=threading.Lock()
        )
        repo.upsert_saved_entry(
            canonical_id="canon-1",
            entry={"id": 1, "title": "Article 1", "url": "https://example.com/1"},
            feed={},
            now_ts=1000,
        )
        repo.upsert_saved_entry(
            canonical_id="canon-2",
            entry={"id": 2, "title": "Article 2", "url": "https://example.com/2"},
            feed={"title": "Known Feed"},
            now_ts=1001,
        )

        missing = repo.list_missing_feed_title(limit=10)
        assert len(missing) == 1
        assert missing[0]["canonical_id"] == "canon-1"
        assert repo.update_feed_title(missing[0]["id"], "Recovered Feed") is True

        rows = repo.search_by_title("article", mode="contains", limit=10, offset=0)
        row = [r for r in rows if r["canonical_id"] == "canon-1"][0]
        assert row["feed_title"] == "Recovered Feed"

    def test_upsert_saved_entry_handles_optional_integer_entry_id(self):
        repo = SavedEntriesRepositorySQLite(
            path=str(TMP_DIR / "saved_entries_optional_int.db"), lock=threading.Lock()
        )
        repo.upsert_saved_entry(
            canonical_id="canon-str",
            entry={"id": " 123 ", "title": "String Entry ID", "url": "https://example.com/s"},
            feed={"title": "Feed"},
            now_ts=1000,
        )
        repo.upsert_saved_entry(
            canonical_id="canon-bool",
            entry={"id": True, "title": "Boolean Entry ID", "url": "https://example.com/b"},
            feed={"title": "Feed"},
            now_ts=1001,
        )
        repo.upsert_saved_entry(
            canonical_id="canon-text",
            entry={"id": "abc", "title": "Text Entry ID", "url": "https://example.com/t"},
            feed={"title": "Feed"},
            now_ts=1002,
        )
        repo.upsert_saved_entry(
            canonical_id="canon-none",
            entry={"id": None, "title": "None Entry ID", "url": "https://example.com/n"},
            feed={"title": "Feed"},
            now_ts=1003,
        )

        rows = repo.search_by_title("entry id", mode="contains", limit=10, offset=0)
        by_canonical_id = {row["canonical_id"]: row for row in rows}

        assert by_canonical_id["canon-str"]["entry_id"] == 123
        assert by_canonical_id["canon-bool"]["entry_id"] is None
        assert by_canonical_id["canon-text"]["entry_id"] is None
        assert by_canonical_id["canon-none"]["entry_id"] is None
