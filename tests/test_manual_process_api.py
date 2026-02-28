import json
import unittest
from unittest.mock import MagicMock, patch

import miniflux
import requests

from common.config import Config
from myapp import create_app


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def make_config():
    return Config.from_dict({"miniflux": {}, "llm": {"max_workers": 1}})


def make_response(status_code: int, json_body=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status_code
    if json_body is not None:
        r._content = json.dumps(json_body).encode("utf-8")
        r.headers["Content-Type"] = "application/json"
    return r


class TestManualProcessAPI(unittest.TestCase):
    def test_returns_400_when_entry_id_missing(self):
        config = make_config()
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/manual-process",
                data=json.dumps({}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")

    def test_returns_400_when_entry_id_invalid(self):
        config = make_config()
        app = create_app(
            config,
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/manual-process",
                data=json.dumps({"entry_id": "abc"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "error")

    def test_returns_404_when_miniflux_entry_not_found(self):
        config = make_config()
        miniflux_client = MagicMock()
        miniflux_client.get_entry.side_effect = miniflux.ResourceNotFound(
            make_response(404, {"error_message": "not found"})
        )
        app = create_app(
            config,
            miniflux_client=miniflux_client,
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/manual-process",
                data=json.dumps({"entry_id": 4889}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "message": "entry not found", "entry_id": "4889"},
        )

    def test_returns_502_when_miniflux_unauthorized(self):
        config = make_config()
        miniflux_client = MagicMock()
        miniflux_client.get_entry.side_effect = miniflux.AccessUnauthorized(
            make_response(401, {"error_message": "unauthorized"})
        )
        app = create_app(
            config,
            miniflux_client=miniflux_client,
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.test_client() as client:
            response = client.post(
                "/miniflux-ai/manual-process",
                data=json.dumps({"entry_id": 1}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["status"], "error")
        self.assertEqual(response.get_json()["message"], "miniflux unauthorized")

    def test_returns_ok_when_processing_succeeds(self):
        config = make_config()
        miniflux_client = MagicMock()
        miniflux_client.get_entry.return_value = {"id": 123, "title": "t", "content": "c"}
        mock_batch = MagicMock(return_value={"failures": []})
        app = create_app(
            config,
            miniflux_client=miniflux_client,
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with patch("myapp.__init__.process_entries_batch", mock_batch):
            with app.test_client() as client:
                response = client.post(
                    "/miniflux-ai/manual-process",
                    data=json.dumps({"entry_id": 123}),
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["entry_id"], "123")
        self.assertIn("trace_id", payload)
        self.assertTrue(payload["trace_id"])
        batch_entries = mock_batch.call_args.args[1]
        self.assertEqual(len(batch_entries), 1)
        self.assertEqual(batch_entries[0].get("_trace_id"), payload["trace_id"])
