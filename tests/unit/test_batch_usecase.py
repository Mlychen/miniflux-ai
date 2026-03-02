import threading

from app.infrastructure.config import Config
from app.application.ingest_service import process_entries_batch


class DummyLogger:
    def __init__(self):
        self.errors = []
        self._lock = threading.Lock()

    def error(self, *args, **kwargs):
        with self._lock:
            self.errors.append((args, kwargs))


def test_returns_zero_when_entries_empty():
    config = Config.from_dict({"llm": {"max_workers": 2}})
    logger = DummyLogger()
    calls = []

    def processor(*args, **kwargs):
        calls.append(1)

    result = process_entries_batch(
        config,
        [],
        miniflux_client=object(),
        entry_processor=processor,
        llm_client=object(),
        logger=logger,
    )

    assert result == {"total": 0, "failures": 0}
    assert calls == []
    assert logger.errors == []


def test_collects_failures_and_keeps_processing():
    config = Config.from_dict({"llm": {"max_workers": 4}})
    logger = DummyLogger()
    entries = [{"id": 1}, {"id": 2}, {"id": 3}]
    seen = []
    seen_lock = threading.Lock()

    def processor(miniflux_client, entry, llm_client, log):
        with seen_lock:
            seen.append(entry["id"])
        if entry["id"] == 2:
            raise RuntimeError("boom")

    result = process_entries_batch(
        config,
        entries,
        miniflux_client=object(),
        entry_processor=processor,
        llm_client=object(),
        logger=logger,
    )

    assert result["total"] == 3
    assert result["failures"] == 1
    assert set(seen) == {1, 2, 3}
    assert len(logger.errors) >= 1
