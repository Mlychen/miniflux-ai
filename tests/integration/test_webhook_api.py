import hashlib
import hmac
import json
from pathlib import Path

from assert_utils import AssertMixin
from common.config import Config
from common.task_store_sqlite import TaskStoreSQLite
from myapp import create_app


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


def make_config(webhook_secret):
    miniflux = {}
    if webhook_secret is not None:
        miniflux["webhook_secret"] = webhook_secret

    return Config.from_dict(
        {
            "miniflux": miniflux,
            "llm": {"max_workers": 2},
        }
    )


def make_payload(count=2):
    return {
        "feed": {
            "site_url": "https://example.com",
            "category": {"title": "News"},
        },
        "entries": [
            {
                "id": idx,
                "created_at": "2026-02-25T00:00:00Z",
                "title": f"title-{idx}",
                "url": f"https://example.com/{idx}",
                "content": f"content-{idx}",
            }
            for idx in range(1, count + 1)
        ],
    }


def sign_payload(secret, payload_bytes):
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


class TestWebhookAPI(AssertMixin):
    def test_rejects_request_when_webhook_secret_missing(self):
        config = make_config(webhook_secret=None)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": "any-signature"},
            )

        self.assertEqual(response.status_code, 403)

    def test_rejects_request_when_signature_missing(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)

    def test_rejects_request_when_signature_invalid(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": "invalid"},
            )

        self.assertEqual(response.status_code, 403)

    def test_returns_500_when_task_store_missing(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "task store not configured"},
        )

    def test_returns_400_when_payload_invalid(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = {"entries": {"id": 1}, "feed": {"site_url": "https://example.com"}}
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "invalid payload"},
        )

    def test_returns_200_when_save_entry_event(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )
        payload = {"event_type": "save_entry"}
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"status": "ignored", "reason": "save_entry not processed"},
        )


class TestWebhookTaskStoreIntegration(AssertMixin):
    def setup_method(self):
        self.tmp_dir = Path(__file__).resolve().parent / ".tmp_webhook_task_store"
        self.tmp_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in self.tmp_dir.glob("*"):
            if p.is_file():
                p.unlink()

    def test_webhook_returns_202_and_persists_tasks_when_task_store_provided(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        task_store = TaskStoreSQLite(path=str(self.tmp_dir / "tasks.db"))

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=task_store,
        )

        payload = make_payload(count=2)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 202)
        result = response.get_json()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["accepted"], 2)
        self.assertEqual(result["duplicates"], 0)
        self.assertTrue(result["trace_id"])

        tasks = task_store.list_tasks()
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(task.trace_id == result["trace_id"] for task in tasks))

    def test_webhook_task_store_deduplicates_by_canonical_id(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        task_store = TaskStoreSQLite(path=str(self.tmp_dir / "tasks_dedup.db"))

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=task_store,
        )

        payload = {
            "feed": {"site_url": "https://example.com", "category": {"title": "News"}},
            "entries": [
                {
                    "id": 1,
                    "created_at": "2026-02-25T00:00:00Z",
                    "title": "same",
                    "url": "https://example.com/x/",
                    "content": "content-a",
                },
                {
                    "id": 2,
                    "created_at": "2026-02-25T00:00:00Z",
                    "title": "same",
                    "url": "https://example.com/x",
                    "content": "content-b",
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 202)
        result = response.get_json()
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertTrue(result["trace_id"])
        self.assertEqual(len(task_store.list_tasks()), 1)

    def test_webhook_task_store_uses_trace_id_from_payload_when_provided(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        task_store = TaskStoreSQLite(path=str(self.tmp_dir / "tasks_trace_id.db"))

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=task_store,
        )

        payload = make_payload(count=1)
        payload["trace_id"] = "trace-from-payload"
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 202)
        result = response.get_json()
        self.assertEqual(result["trace_id"], "trace-from-payload")
        tasks = task_store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].trace_id, "trace-from-payload")

    def test_webhook_task_store_header_trace_id_overrides_payload_trace_id(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        task_store = TaskStoreSQLite(path=str(self.tmp_dir / "tasks_trace_id_header.db"))

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=task_store,
        )

        payload = make_payload(count=1)
        payload["trace_id"] = "trace-from-payload"
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={
                    "X-Miniflux-Signature": signature,
                    "X-Trace-Id": "trace-from-header",
                },
            )

        self.assertEqual(response.status_code, 202)
        result = response.get_json()
        self.assertEqual(result["trace_id"], "trace-from-header")
        tasks = task_store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].trace_id, "trace-from-header")

    def test_webhook_returns_500_when_task_store_persist_fails(self):
        class FailingTaskStore:
            def create_task(self, **kwargs):
                raise RuntimeError("db unavailable")

        secret = "test-secret"
        config = make_config(webhook_secret=secret)

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            task_store=FailingTaskStore(),
        )

        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/webhook/entries",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(), {"status": "error", "message": "task persistence failed"}
        )
