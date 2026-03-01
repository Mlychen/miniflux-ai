import json
import threading
from types import SimpleNamespace

from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.config import Config
from common.entries_repository_sqlite import EntriesRepositorySQLite
from myapp import create_app


def build_app(tmp_path, llm_client=None, entries_repo=None):
    config = Config.from_dict({"debug": {"enabled": False}})
    if entries_repo is None:
        entries_repo = EntriesRepositorySQLite(
            path=str(tmp_path / "entries.db"), lock=threading.Lock()
        )
    ai_repo = AiNewsRepositorySQLite(
        path=str(tmp_path / "ai.db"), lock=threading.Lock()
    )
    if llm_client is None:
        llm_client = SimpleNamespace()
    app = create_app(
        config,
        miniflux_client=SimpleNamespace(),
        llm_client=llm_client,
        logger=None,
        entry_processor=lambda *a, **k: None,
        entries_repository=entries_repo,
        ai_news_repository=ai_repo,
    )
    return app, entries_repo


def write_process_log(tmp_path, records):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "manual-process.log"
    with open(log_file, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_processed_entries_backfills_trace_info(tmp_path, monkeypatch):
    app, entries_repo = build_app(tmp_path)
    canonical_id = "canon-1"
    entries_repo.append_summary_items(
        [
            {
                "id": canonical_id,
                "datetime": "2026-02-25T00:00:00Z",
                "title": "title-1",
                "content": "content-1",
                "url": "https://example.com/1",
            }
        ]
    )
    trace_id = "trace-12345678901234567890"
    records = [
        {
            "timestamp": "2026-02-25T01:00:00Z",
            "entry_id": 123,
            "trace_id": trace_id,
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 5000,
            "data": {"canonical_id": canonical_id},
        }
    ]
    write_process_log(tmp_path, records)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/processed-entries?limit=10&offset=0")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["total"] == 1
    row = payload["entries"][0]
    assert row["canonical_id"] == canonical_id
    assert row["entry_id"] == "123"
    assert row["trace_id"] == trace_id


def test_process_trace_entry_id_and_trace_detail(tmp_path, monkeypatch):
    app, _ = build_app(tmp_path)
    trace_id = "trace-12345678901234567890"
    records = [
        {
            "timestamp": "2026-02-25T01:00:00Z",
            "entry_id": 123,
            "trace_id": trace_id,
            "stage": "process",
            "action": "start",
            "status": "pending",
            "duration_ms": None,
            "data": {"canonical_id": "canon-1"},
        },
        {
            "timestamp": "2026-02-25T01:00:05Z",
            "entry_id": 123,
            "trace_id": trace_id,
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 5000,
            "data": {"canonical_id": "canon-1"},
        },
    ]
    write_process_log(tmp_path, records)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    list_response = client.get("/miniflux-ai/user/process-trace/123")
    list_payload = list_response.get_json()
    assert list_response.status_code == 200
    assert list_payload["status"] == "ok"
    assert list_payload["type"] == "list"
    assert list_payload["traces"][0]["trace_id"] == trace_id

    detail_response = client.get(f"/miniflux-ai/user/process-trace/{trace_id}")
    detail_payload = detail_response.get_json()
    assert detail_response.status_code == 200
    assert detail_payload["type"] == "detail"
    assert detail_payload["summary"]["entry_id"] == "123"
    assert len(detail_payload["stages"]) == 2


def test_process_history(tmp_path, monkeypatch):
    app, _ = build_app(tmp_path)
    records = [
        {
            "timestamp": "2026-02-25T01:00:00Z",
            "entry_id": 123,
            "trace_id": "trace-1",
            "stage": "process",
            "action": "start",
            "status": "pending",
            "duration_ms": None,
            "data": {},
        },
        {
            "timestamp": "2026-02-25T01:00:05Z",
            "entry_id": 123,
            "trace_id": "trace-1",
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 5000,
            "data": {},
        },
        {
            "timestamp": "2026-02-25T02:00:00Z",
            "entry_id": 456,
            "trace_id": "trace-2",
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 3000,
            "data": {},
        },
    ]
    write_process_log(tmp_path, records)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/process-history?limit=10")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["total"] == 2
    assert {row["trace_id"] for row in payload["traces"]} == {"trace-1", "trace-2"}


def test_processed_entries_returns_500_when_repository_fails(tmp_path):
    class FailingEntriesRepository:
        def read_all(self):
            raise RuntimeError("read failure")

    app, _ = build_app(tmp_path, entries_repo=FailingEntriesRepository())
    client = app.test_client()
    response = client.get("/miniflux-ai/user/processed-entries")
    payload = response.get_json()
    assert response.status_code == 500
    assert payload["status"] == "error"
    assert payload["message"] == "read failure"


def test_processed_entries_normalizes_limit_and_offset(tmp_path):
    app, _ = build_app(tmp_path)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/processed-entries?limit=abc&offset=-3")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["limit"] == 100
    assert payload["offset"] == 0


def test_llm_pool_metrics_returns_400_when_unavailable(tmp_path):
    app, _ = build_app(tmp_path, llm_client=SimpleNamespace())
    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/metrics")
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["message"] == "llm pool metrics unavailable"


def test_llm_pool_metrics_returns_ok(tmp_path):
    class DummyPool:
        def get_metrics(self):
            return {"pending": 1, "failed": 2}

    app, _ = build_app(tmp_path, llm_client=DummyPool())
    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/metrics")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["metrics"]["failed"] == 2


def test_llm_pool_failed_entries_returns_400_when_unavailable(tmp_path):
    app, _ = build_app(tmp_path, llm_client=SimpleNamespace())
    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/failed-entries")
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["message"] == "llm pool failed-entries unavailable"


def test_llm_pool_failed_entries_handles_invalid_limit_and_missing_summaries(tmp_path):
    class DummyPool:
        def __init__(self):
            self.last_limit = None

        def get_failed_entries(self, limit=100):
            self.last_limit = limit
            return {
                "canon-1:entry-1": {"status": "failed"},
                "ai-news-2026-01": {"status": "failed"},
            }

    class FailingEntriesRepository:
        def read_all(self):
            raise RuntimeError("read failure")

    pool = DummyPool()
    app, _ = build_app(
        tmp_path, llm_client=pool, entries_repo=FailingEntriesRepository()
    )
    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/failed-entries?limit=-2")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert pool.last_limit == 1
    items = payload["items"]
    assert len(items) == 2
    item_keys = {item["entry_key"] for item in items}
    assert item_keys == {"canon-1:entry-1", "ai-news-2026-01"}
