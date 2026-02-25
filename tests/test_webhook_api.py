import hashlib
import hmac
import json
import threading
import unittest

from common.config import Config
from myapp import create_app


class DummyLogger:
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


if __name__ == "__main__":
    unittest.main()
