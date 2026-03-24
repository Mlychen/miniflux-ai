import json
import threading
from types import SimpleNamespace

from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.config import Config
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.interfaces.http import create_app


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
            "data": {"canonical_id": "canon-1", "ai_category": "AI新闻"},
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

    # 按 trace_id 查询现在返回批次模式
    batch_response = client.get(f"/miniflux-ai/user/process-trace/{trace_id}")
    batch_payload = batch_response.get_json()
    assert batch_response.status_code == 200
    assert batch_payload["type"] == "batch"
    assert batch_payload["trace_id"] == trace_id
    assert batch_payload["summary"]["total_entries"] == 1
    assert batch_payload["summary"]["success_count"] == 1
    assert len(batch_payload["entries"]) == 1
    assert batch_payload["entries"][0]["canonical_id"] == "canon-1"

    # 详细 stages 通过 canonical-trace API 获取
    canonical_response = client.get(f"/miniflux-ai/user/canonical-trace/canon-1?trace_id={trace_id}")
    canonical_payload = canonical_response.get_json()
    assert canonical_response.status_code == 200
    assert canonical_payload["type"] == "detail"
    assert canonical_payload["canonical_id"] == "canon-1"
    assert len(canonical_payload["stages"]) == 2


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
            "data": {"canonical_id": "canon-1"},
        },
        {
            "timestamp": "2026-02-25T01:00:05Z",
            "entry_id": 123,
            "trace_id": "trace-1",
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 5000,
            "data": {"canonical_id": "canon-1"},
        },
        {
            "timestamp": "2026-02-25T02:00:00Z",
            "entry_id": 456,
            "trace_id": "trace-2",
            "stage": "process",
            "action": "complete",
            "status": "ok",
            "duration_ms": 3000,
            "data": {"canonical_id": "canon-2"},
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
    # 新的 API 返回批次聚合信息
    trace_ids = {row["trace_id"] for row in payload["traces"]}
    assert trace_ids == {"trace-1", "trace-2"}
    # 验证批次字段
    for row in payload["traces"]:
        assert "total_entries" in row
        assert "success_count" in row
        assert "error_count" in row
        assert "status" in row


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


def test_llm_pool_failed_entries_returns_400_when_task_store_unavailable(tmp_path):
    """当 TaskStore 不可用时返回 400。"""
    app, _ = build_app(tmp_path, llm_client=SimpleNamespace())
    # build_app 默认不传入 task_store，所以会是 None
    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/failed-entries")
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["message"] == "task store unavailable"


def test_llm_pool_failed_entries_returns_tasks_from_task_store(tmp_path):
    """从 TaskStore 获取失败任务。"""
    from app.infrastructure.task_store_sqlite import TaskStoreSQLite

    task_store = TaskStoreSQLite(path=str(tmp_path / "tasks.db"), lock=threading.Lock())
    # 创建两个失败任务
    task_store.create_task("canon-1", {"entry_id": 1}, now_ts=1000)
    task_store.create_task("ai-news-2026-01", {"entry_id": 2}, now_ts=1000)

    # 标记第一个为 retryable
    task = task_store.get_task_by_canonical_id("canon-1")
    task_store.mark_retryable(task.id, "test error", retry_delay_seconds=30)

    # 标记第二个为 dead
    task2 = task_store.get_task_by_canonical_id("ai-news-2026-01")
    task_store.mark_dead(task2.id, "permanent error")

    app, _ = build_app(tmp_path)
    # 手动注入 task_store
    app.config["APP_SERVICES"] = app.config["APP_SERVICES"].__class__(
        config=app.config["APP_SERVICES"].config,
        miniflux_client=app.config["APP_SERVICES"].miniflux_client,
        llm_client=app.config["APP_SERVICES"].llm_client,
        logger=app.config["APP_SERVICES"].logger,
        entry_processor=app.config["APP_SERVICES"].entry_processor,
        entries_repository=app.config["APP_SERVICES"].entries_repository,
        ai_news_repository=app.config["APP_SERVICES"].ai_news_repository,
        saved_entries_repository=app.config["APP_SERVICES"].saved_entries_repository,
        summary_archive_repository=app.config["APP_SERVICES"].summary_archive_repository,
        task_store=task_store,
    )

    client = app.test_client()
    response = client.get("/miniflux-ai/user/llm-pool/failed-entries")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    items = payload["items"]
    assert len(items) == 2
    canonical_ids = {item["canonical_id"] for item in items}
    assert canonical_ids == {"canon-1", "ai-news-2026-01"}
    # 检查状态字段
    statuses = {item["canonical_id"]: item["status"] for item in items}
    assert statuses["canon-1"] == "retryable"
    assert statuses["ai-news-2026-01"] == "dead"
