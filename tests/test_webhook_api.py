import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest.mock import MagicMock

from common.config import Config
from core.queue import InMemoryQueueBackend, WebhookQueue
from myapp import create_app


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
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


class TestWebhookAPI(unittest.TestCase):
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
                "/api/miniflux-ai",
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
                "/api/miniflux-ai",
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
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": "invalid"},
            )

        self.assertEqual(response.status_code, 403)

    def test_accepts_valid_signature_and_processes_each_entry(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        calls = []
        lock = threading.Lock()

        def entry_processor(miniflux_client, entry, llm_client, logger):
            with lock:
                calls.append(
                    {
                        "entry_id": entry["id"],
                        "has_feed": "feed" in entry,
                    }
                )

        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=entry_processor,
        )
        payload = make_payload(count=3)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        self.assertEqual(len(calls), 3)
        self.assertEqual({c["entry_id"] for c in calls}, {1, 2, 3})
        self.assertTrue(all(c["has_feed"] for c in calls))

    def test_returns_500_when_entry_processor_raises(self):
        secret = "test-secret"
        config = make_config(webhook_secret=secret)

        def entry_processor(*args, **kwargs):
            raise RuntimeError("processor-failed")

        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=entry_processor,
        )
        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"status": "error"})


class TestWebhookQueueIntegration(unittest.TestCase):
    """Test webhook queue integration."""

    def test_queue_stored_in_app_config_when_provided(self):
        """Verify queue is stored in Flask app.config when webhook_queue is passed."""
        config = make_config(webhook_secret="test-secret")
        queue_backend = InMemoryQueueBackend(max_size=100)
        webhook_queue = WebhookQueue(backend=queue_backend, workers=2)

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            webhook_queue=webhook_queue,
        )

        self.assertIn("WEBHOOK_QUEUE", app.config)
        self.assertIs(app.config["WEBHOOK_QUEUE"], webhook_queue)

    def test_no_queue_in_app_config_when_not_provided(self):
        """Verify app.config does not have WEBHOOK_QUEUE when not provided."""
        config = make_config(webhook_secret="test-secret")

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        # Queue should be None or not present
        self.assertIsNone(app.config.get("WEBHOOK_QUEUE"))

    def test_webhook_returns_202_when_queue_provided(self):
        """Verify webhook returns 202 Accepted when queue is configured."""
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        queue_backend = InMemoryQueueBackend(max_size=100)
        webhook_queue = WebhookQueue(backend=queue_backend, workers=2)

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            webhook_queue=webhook_queue,
        )

        payload = make_payload(count=2)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        with app.test_client() as client:
            response = client.post(
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"status": "accepted"})

    def test_webhook_returns_503_when_queue_full(self):
        """Verify webhook returns 503 when queue is full."""
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        # Create queue with max_size=1
        queue_backend = InMemoryQueueBackend(max_size=1)
        webhook_queue = WebhookQueue(backend=queue_backend, workers=1)

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            webhook_queue=webhook_queue,
        )

        payload = make_payload(count=1)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        # Fill the queue
        webhook_queue.enqueue({"entries": [], "feed": {}})
        self.assertTrue(webhook_queue.is_full)

        with app.test_client() as client:
            response = client.post(
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 503)
        result = response.get_json()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "queue full")

    def test_queue_processes_items_async(self):
        """Verify items are enqueued and can be processed by consumer."""
        secret = "test-secret"
        config = make_config(webhook_secret=secret)
        queue_backend = InMemoryQueueBackend(max_size=100)
        webhook_queue = WebhookQueue(backend=queue_backend, workers=1)

        processed_items = []
        lock = threading.Lock()

        def entry_processor(miniflux_client, entry, llm_client, logger):
            with lock:
                processed_items.append(entry["id"])

        app = create_app(
            config=config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=entry_processor,
            webhook_queue=webhook_queue,
        )

        payload = make_payload(count=3)
        body = json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        # Send webhook request - returns immediately with 202
        with app.test_client() as client:
            response = client.post(
                "/api/miniflux-ai",
                data=body,
                content_type="application/json",
                headers={"X-Miniflux-Signature": signature},
            )

        self.assertEqual(response.status_code, 202)

        # Verify item is enqueued
        self.assertEqual(webhook_queue.size(), 1)

        # Start consumer and process the item
        from core.process_entries_batch import process_entries_batch

        def processor_fn(task):
            batch_entries = task.get("entries", [])
            feed = task.get("feed", {})
            batch_entries = [dict(entry, feed=feed) for entry in batch_entries]
            process_entries_batch(
                config,
                batch_entries,
                MagicMock(),  # miniflux_client
                entry_processor,
                MagicMock(),  # llm_client
                DummyLogger(),
            )

        webhook_queue.start(processor_fn)

        # Wait for processing
        time.sleep(0.5)
        webhook_queue.stop()

        # Verify all entries were processed
        self.assertEqual(len(processed_items), 3)
        self.assertEqual(set(processed_items), {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
