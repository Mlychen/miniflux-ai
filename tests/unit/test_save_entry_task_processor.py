from types import SimpleNamespace

import main


class DummySavedEntriesRepository:
    def __init__(self):
        self.calls = []

    def upsert_saved_entry(self, canonical_id, entry, feed=None):
        self.calls.append(
            {
                "canonical_id": canonical_id,
                "entry": entry,
                "feed": feed,
            }
        )
        return True


class DummyMinifluxClient:
    def __init__(self, feeds):
        self._feeds = feeds
        self.calls = 0

    def get_feeds(self):
        self.calls += 1
        return self._feeds


def test_create_task_record_processor_handles_save_entry_task():
    saved_repo = DummySavedEntriesRepository()
    services = SimpleNamespace(
        config=object(),
        logger=object(),
        miniflux_client=object(),
        llm_client=object(),
        entry_processor=lambda *a, **k: None,
        saved_entries_repository=saved_repo,
    )
    processor = main.create_task_record_processor(services)
    task = SimpleNamespace(
        canonical_id="canon-save-1",
        payload={
            "task_type": "save_entry",
            "entry": {"id": 1, "title": "Saved Title", "url": "https://example.com"},
            "feed": {"title": "Tech"},
        },
    )

    processor(task)

    assert len(saved_repo.calls) == 1
    assert saved_repo.calls[0]["canonical_id"] == "canon-save-1"
    assert saved_repo.calls[0]["entry"]["title"] == "Saved Title"


def test_create_task_record_processor_resolves_feed_title_by_feed_id():
    saved_repo = DummySavedEntriesRepository()
    miniflux_client = DummyMinifluxClient(
        feeds=[
            {"id": 100, "title": "AI Weekly"},
            {"id": 101, "title": "Infra"},
        ]
    )
    services = SimpleNamespace(
        config=object(),
        logger=object(),
        miniflux_client=miniflux_client,
        llm_client=object(),
        entry_processor=lambda *a, **k: None,
        saved_entries_repository=saved_repo,
    )
    processor = main.create_task_record_processor(services)
    task = SimpleNamespace(
        canonical_id="canon-save-2",
        payload={
            "task_type": "save_entry",
            "entry": {"id": 2, "title": "Saved Title 2", "url": "https://example.com/2", "feed_id": 100},
            "feed": {},
        },
    )

    processor(task)

    assert len(saved_repo.calls) == 1
    assert saved_repo.calls[0]["feed"]["title"] == "AI Weekly"
    assert miniflux_client.calls == 1
