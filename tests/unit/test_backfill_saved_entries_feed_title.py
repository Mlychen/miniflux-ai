from scripts import backfill_saved_entries_feed_title as backfill_module


class FakeConfig:
    storage_sqlite_path = "runtime/test.db"
    miniflux_base_url = "http://example.com"
    miniflux_api_key = "token"


class FakeRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.updated = []

    def list_missing_feed_title(self, limit=200):
        if not self.rows:
            return []
        batch = self.rows[:limit]
        self.rows = self.rows[limit:]
        return batch

    def update_feed_title(self, row_id, title):
        self.updated.append((row_id, title))
        return True


class FakeMinifluxGateway:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key

    def get_feeds(self):
        return [{"id": 7, "title": "Feed Seven"}]

    def get_entry(self, entry_id):
        return {"id": entry_id, "feed_id": 7}


def test_run_backfill_skips_rows_with_invalid_row_id(monkeypatch):
    repository = FakeRepository(
        [
            {"id": "bad-id", "entry_id": 101, "canonical_id": "101"},
            {"id": "2", "entry_id": None, "canonical_id": "202"},
        ]
    )

    monkeypatch.setattr(backfill_module.Config, "from_file", lambda _: FakeConfig())
    monkeypatch.setattr(
        backfill_module,
        "SavedEntriesRepositorySQLite",
        lambda path: repository,
    )
    monkeypatch.setattr(backfill_module, "MinifluxGateway", FakeMinifluxGateway)

    stats = backfill_module.run_backfill("config.yml", batch_size=10, max_batches=1)

    assert stats == {
        "scanned": 2,
        "updated": 1,
        "skipped": 1,
        "failed": 0,
        "batches": 1,
    }
    assert repository.updated == [(2, "Feed Seven")]


def test_run_backfill_skips_when_source_title_is_missing(monkeypatch):
    class EmptyFeedGateway(FakeMinifluxGateway):
        def get_feeds(self):
            return []

        def get_entry(self, entry_id):
            return {"id": entry_id, "feed_id": 999}

    repository = FakeRepository([{"id": 3, "entry_id": 303, "canonical_id": "303"}])

    monkeypatch.setattr(backfill_module.Config, "from_file", lambda _: FakeConfig())
    monkeypatch.setattr(
        backfill_module,
        "SavedEntriesRepositorySQLite",
        lambda path: repository,
    )
    monkeypatch.setattr(backfill_module, "MinifluxGateway", EmptyFeedGateway)

    stats = backfill_module.run_backfill("config.yml", batch_size=10, max_batches=1)

    assert stats == {
        "scanned": 1,
        "updated": 0,
        "skipped": 1,
        "failed": 0,
        "batches": 1,
    }
    assert repository.updated == []
