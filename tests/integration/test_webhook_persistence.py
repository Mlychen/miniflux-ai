import hashlib
import hmac
import json
from types import SimpleNamespace

from app.domain.task_store import TASK_PENDING
from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.interfaces.http import create_app


def test_webhook_persists_pending_task(tmp_path, base_config, dummy_logger):
    task_store = TaskStoreSQLite(path=str(tmp_path / "tasks.db"))
    app = create_app(
        base_config,
        miniflux_client=SimpleNamespace(),
        llm_client=SimpleNamespace(),
        logger=dummy_logger,
        entry_processor=lambda *a, **k: None,
        task_store=task_store,
    )
    payload = {
        "event_type": "new_entries",
        "entries": [
            {"id": 1, "title": "hello", "url": "https://example.com/1", "content": "a"}
        ],
        "feed": {"site_url": "https://example.com", "title": "Example"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        base_config.miniflux_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    client = app.test_client()
    response = client.post(
        "/miniflux-ai/webhook/entries",
        data=body,
        headers={"X-Miniflux-Signature": signature},
        content_type="application/json",
    )
    assert response.status_code == 202
    tasks = task_store.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.status == TASK_PENDING
    assert task.payload["entry"]["id"] == 1
