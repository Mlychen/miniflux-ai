import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.infrastructure.config import Config
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.application.ingest_service import fetch_unread_entries
from app.domain.processor import process_entry


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_concurrency"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class DummyMinifluxUpdateClient:
    def __init__(self):
        self.updated = []
        self._lock = threading.Lock()

    def update_entry(self, entry_id, **kwargs):
        with self._lock:
            self.updated.append((entry_id, kwargs))


class DummyMinifluxFetchClient:
    def __init__(self, entries):
        self._entries = entries

    def get_entries(self, status, limit):
        return {"entries": self._entries}


class DummyLLMGateway:
    def get_result(self, prompt, request, logger=None):
        if "Return a JSON object with fields:" in (prompt or ""):
            return json.dumps(
                {
                    "summary": f"summary::{request}",
                    "ai_category": "Tech",
                    "subject": "Test",
                    "subject_type": "Org",
                    "region": "Global",
                    "event_type": "Update",
                    "group_hint": "Tech / Test / Global",
                    "confidence": 0.8,
                }
            )
        return f"summary::{request}"


def make_summary_config():
    return Config.from_dict(
        {
            "agents": {
                "summary": {
                    "title": "AI summary: ",
                    "prompt": "summarize",
                    "style_block": True,
                    "allow_list": None,
                    "deny_list": None,
                }
            }
        }
    )


class TestConcurrencyIntegrity:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_process_entry_parallel_writes_are_complete(self):
        sqlite_file = TMP_DIR / "entries_parallel.db"

        config = make_summary_config()
        client = DummyMinifluxUpdateClient()
        logger = DummyLogger()
        file_lock = threading.Lock()
        entries = [
            {
                "id": idx,
                "created_at": "2026-02-25T00:00:00Z",
                "title": f"title-{idx}",
                "url": f"https://example.com/{idx}",
                "content": f"raw-content-{idx}",
                "feed": {
                    "site_url": "https://example.com",
                    "category": {"title": "News"},
                },
            }
            for idx in range(1, 61)
        ]

        llm_gateway = DummyLLMGateway()
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file), lock=file_lock)
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(
                    process_entry,
                    client,
                    entry,
                    config,
                    llm_gateway,
                    logger,
                    entries_repository,
                )
                for entry in entries
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    if "database is locked" in str(exc).lower():
                        raise AssertionError(f"database is locked: {exc}") from exc
                    raise

        saved = entries_repository.read_all()
        assert len(saved) == len(entries)
        assert {item["url"] for item in saved} == {entry["url"] for entry in entries}
        assert len(client.updated) == len(entries)

    def test_fetch_unread_entries_processes_each_entry(self):
        config = Config.from_dict({"llm": {"max_workers": 3}})
        entries = [{"id": 1}, {"id": 2}, {"id": 3}]
        client = DummyMinifluxFetchClient(entries)
        logger = DummyLogger()

        seen_ids = []
        capture_lock = threading.Lock()

        def entry_processor(miniflux_client, entry, llm_client, log):
            with capture_lock:
                seen_ids.append(entry["id"])

        fetch_unread_entries(
            config,
            client,
            entry_processor,
            llm_client=object(),
            logger=logger,
        )

        assert set(seen_ids) == {1, 2, 3}
