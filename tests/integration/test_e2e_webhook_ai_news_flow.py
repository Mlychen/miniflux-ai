import hashlib
import hmac
import json
import threading
import time
from types import SimpleNamespace

from app.application.news_service import generate_daily_news
from app.domain.processor import InMemoryProcessedNewsIds, build_rate_limited_processor
from app.domain.task_store import TASK_DONE, TASK_PENDING
from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.config import Config
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite
from app.infrastructure.summary_archive_repository_sqlite import (
    SummaryArchiveRepositorySQLite,
)
from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.application.worker_service import TaskWorker
from app.interfaces.http import create_app
from main import create_task_record_processor


class FakeMinifluxClient:
    def __init__(self):
        self.updated = []
        self.refreshed = []
        self.feeds = [{"id": 77, "title": "Newsᴬᴵ for you"}]

    def update_entry(self, entry_id, **kwargs):
        self.updated.append((entry_id, kwargs))

    def get_feeds(self):
        return list(self.feeds)

    def refresh_feed(self, feed_id):
        self.refreshed.append(feed_id)


class DeterministicLLMClient:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def get_result(self, prompt, request, logger=None):
        with self._lock:
            self.calls.append((prompt, request))
            text_prompt = str(prompt or "")
            if "Return a JSON object with fields" in text_prompt:
                return json.dumps(
                    {
                        "summary": "hello-summary",
                        "ai_category": "科技",
                        "subject": "OpenAI",
                        "subject_type": "公司",
                        "region": "美国",
                        "event_type": "发布",
                        "group_hint": "科技 / OpenAI / 美国",
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
            if text_prompt == "greeting-prompt":
                return "Good morning from AI"
            if text_prompt == "summary-block-prompt":
                return "### Grouped News\n- Example item"
            if text_prompt == "summary-prompt":
                return "Daily summary body"
            raise AssertionError(f"Unexpected LLM prompt: {text_prompt}")


def _sign_payload(secret, payload_bytes):
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def _wait_for_task_status(task_store, task_id, expected_status, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = task_store.get_task(task_id)
        if task and task.status == expected_status:
            return task
        time.sleep(0.05)
    return task_store.get_task(task_id)


def _make_config(sqlite_path):
    return Config.from_dict(
        {
            "storage": {"sqlite_path": str(sqlite_path)},
            "miniflux": {
                "webhook_secret": "secret",
                "task_poll_interval": 0.05,
                "task_retry_delay_seconds": 1,
                "task_max_attempts": 3,
                "dedup_marker": "DEDUP-MARKER",
            },
            "llm": {"max_workers": 1, "RPM": 1000},
            "agents": {
                "summary": {
                    "title": "AI summary:",
                    "prompt": "summary-agent-prompt",
                    "style_block": False,
                    "allow_list": None,
                    "deny_list": None,
                }
            },
            "ai_news": {
                "prompts": {
                    "greeting": "greeting-prompt",
                    "summary_block": "summary-block-prompt",
                    "summary": "summary-prompt",
                }
            },
        }
    )


def _make_runtime(tmp_path):
    sqlite_path = tmp_path / "e2e.db"
    config = _make_config(sqlite_path)
    shared_lock = threading.Lock()
    miniflux_client = FakeMinifluxClient()
    llm_client = DeterministicLLMClient()
    task_store = TaskStoreSQLite(path=str(sqlite_path), lock=shared_lock)
    entries_repository = EntriesRepositorySQLite(path=str(sqlite_path), lock=shared_lock)
    ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_path), lock=shared_lock)
    saved_entries_repository = SavedEntriesRepositorySQLite(
        path=str(sqlite_path), lock=shared_lock
    )
    summary_archive_repository = SummaryArchiveRepositorySQLite(
        path=str(sqlite_path), lock=shared_lock
    )
    logger = SimpleNamespace(
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    entry_processor = build_rate_limited_processor(
        config,
        entries_repository=entries_repository,
        processed_entries_repository=entries_repository,
        summary_archive_repository=summary_archive_repository,
        processed_news_ids=InMemoryProcessedNewsIds(),
    )
    app = create_app(
        config=config,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        logger=logger,
        entry_processor=entry_processor,
        entries_repository=entries_repository,
        ai_news_repository=ai_news_repository,
        saved_entries_repository=saved_entries_repository,
        summary_archive_repository=summary_archive_repository,
        task_store=task_store,
    )
    services = SimpleNamespace(
        config=config,
        logger=logger,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        entry_processor=entry_processor,
        entries_repository=entries_repository,
        ai_news_repository=ai_news_repository,
        saved_entries_repository=saved_entries_repository,
        summary_archive_repository=summary_archive_repository,
        task_store=task_store,
    )
    return SimpleNamespace(
        config=config,
        app=app,
        services=services,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        task_store=task_store,
        entries_repository=entries_repository,
        ai_news_repository=ai_news_repository,
        summary_archive_repository=summary_archive_repository,
    )


def _post_webhook(app, payload, secret):
    body = json.dumps(payload).encode("utf-8")
    signature = _sign_payload(secret, body)
    with app.test_client() as client:
        return client.post(
            "/miniflux-ai/webhook/entries",
            data=body,
            headers={"X-Miniflux-Signature": signature},
            content_type="application/json",
        )


def test_webhook_to_ai_news_full_flow(tmp_path):
    runtime = _make_runtime(tmp_path)
    payload = {
        "event_type": "new_entries",
        "feed": {
            "id": 42,
            "site_url": "https://example.com",
            "title": "Example Feed",
            "category": {"title": "News"},
        },
        "entries": [
            {
                "id": 101,
                "created_at": "2026-03-24T01:00:00Z",
                "title": "Example Title",
                "url": "https://example.com/post-1",
                "content": "original content",
            }
        ],
    }

    response = _post_webhook(runtime.app, payload, runtime.config.miniflux_webhook_secret)
    assert response.status_code == 202
    webhook_payload = response.get_json()
    assert webhook_payload["status"] == "accepted"
    assert webhook_payload["accepted"] == 1
    assert webhook_payload["duplicates"] == 0
    assert webhook_payload["trace_id"]

    tasks = runtime.task_store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == TASK_PENDING

    worker = TaskWorker(
        runtime.task_store,
        workers=1,
        poll_interval=0.05,
        base_retry_delay_seconds=1,
    )
    worker.start(create_task_record_processor(runtime.services))
    try:
        done_task = _wait_for_task_status(runtime.task_store, tasks[0].id, TASK_DONE)
        assert done_task is not None
        assert done_task.status == TASK_DONE
    finally:
        worker.stop()

    assert len(runtime.miniflux_client.updated) == 1
    updated_entry_id, updated_kwargs = runtime.miniflux_client.updated[0]
    assert updated_entry_id == 101
    assert "AI summary:" in updated_kwargs["content"]
    assert "original content" in updated_kwargs["content"]

    saved_entries = runtime.entries_repository.read_all()
    assert len(saved_entries) == 1
    assert saved_entries[0]["content"] == "hello-summary"

    canonical_id = done_task.canonical_id
    archived_entries = runtime.summary_archive_repository.get_by_canonical_id(canonical_id)
    assert len(archived_entries) == 1
    assert archived_entries[0]["trace_id"] == webhook_payload["trace_id"]
    assert archived_entries[0]["summary_content"] == "hello-summary"

    generate_daily_news(
        runtime.miniflux_client,
        runtime.config,
        runtime.llm_client,
        runtime.services.logger,
        runtime.ai_news_repository,
        runtime.entries_repository,
    )

    assert runtime.entries_repository.read_all() == []
    archived_after_news = runtime.summary_archive_repository.get_by_canonical_id(
        canonical_id
    )
    assert len(archived_after_news) == 1
    assert runtime.miniflux_client.refreshed == [77]

    with runtime.app.test_client() as client:
        rss_response = client.get("/miniflux-ai/rss/ai-news")

    assert rss_response.status_code == 200
    rss_xml = rss_response.data.decode("utf-8")
    assert "<rss" in rss_xml.lower()
    assert "Powered by miniflux-ai" in rss_xml
    assert "Daily summary body" in rss_xml
    assert runtime.ai_news_repository.consume_latest() == ""


def test_webhook_e2e_deduplicates_same_entry(tmp_path):
    runtime = _make_runtime(tmp_path)
    payload = {
        "event_type": "new_entries",
        "feed": {
            "id": 42,
            "site_url": "https://example.com",
            "title": "Example Feed",
            "category": {"title": "News"},
        },
        "entries": [
            {
                "id": 201,
                "created_at": "2026-03-24T01:00:00Z",
                "title": "Duplicate Title",
                "url": "https://example.com/post-dup",
                "content": "duplicate content",
            }
        ],
    }

    first_response = _post_webhook(
        runtime.app, payload, runtime.config.miniflux_webhook_secret
    )
    second_response = _post_webhook(
        runtime.app, payload, runtime.config.miniflux_webhook_secret
    )

    first_payload = first_response.get_json()
    second_payload = second_response.get_json()
    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_payload["accepted"] == 1
    assert first_payload["duplicates"] == 0
    assert second_payload["accepted"] == 0
    assert second_payload["duplicates"] == 1

    tasks = runtime.task_store.list_tasks()
    assert len(tasks) == 1

    worker = TaskWorker(
        runtime.task_store,
        workers=1,
        poll_interval=0.05,
        base_retry_delay_seconds=1,
    )
    worker.start(create_task_record_processor(runtime.services))
    try:
        done_task = _wait_for_task_status(runtime.task_store, tasks[0].id, TASK_DONE)
        assert done_task is not None
        assert done_task.status == TASK_DONE
    finally:
        worker.stop()

    archived_entries = runtime.summary_archive_repository.get_by_canonical_id(
        done_task.canonical_id
    )
    assert len(archived_entries) == 1
    assert len(runtime.entries_repository.read_all()) == 1
    assert len(runtime.miniflux_client.updated) == 1
