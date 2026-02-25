import threading
import unittest

from common.config import Config
from core.process_entries_batch import process_entries_batch


class DummyLogger:
    def __init__(self):
        self.errors = []
        self._lock = threading.Lock()

    def error(self, *args, **kwargs):
        with self._lock:
            self.errors.append((args, kwargs))


class TestBatchUsecase(unittest.TestCase):
    def test_returns_zero_when_entries_empty(self):
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

        self.assertEqual(result, {"total": 0, "failures": 0})
        self.assertEqual(calls, [])
        self.assertEqual(logger.errors, [])

    def test_collects_failures_and_keeps_processing(self):
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

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["failures"], 1)
        self.assertEqual(set(seen), {1, 2, 3})
        self.assertGreaterEqual(len(logger.errors), 2)


if __name__ == "__main__":
    unittest.main()
