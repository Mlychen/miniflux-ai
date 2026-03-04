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
