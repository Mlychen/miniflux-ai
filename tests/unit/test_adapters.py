import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import miniflux
import pytest
import requests
import urllib3

from app.infrastructure.llm_gateway import LLMGateway
from app.infrastructure.miniflux_gateway import MinifluxGateway, MinifluxGatewayError


class TestMinifluxGateway:
    @staticmethod
    def _response(status_code, payload):
        response = requests.Response()
        response.status_code = status_code
        if payload is not None:
            response._content = json.dumps(payload).encode("utf-8")
            response.headers["Content-Type"] = "application/json"
        return response

    def test_delegates_calls_to_underlying_client(self):
        fake_client = Mock()

        with patch('app.infrastructure.miniflux_gateway.miniflux.Client', return_value=fake_client) as ctor:
            gateway = MinifluxGateway('http://miniflux.local', 'api-key')

        ctor.assert_called_once_with("http://miniflux.local", api_key="api-key")

        gateway.me()
        fake_client.me.assert_called_once_with()

        gateway.get_entries(status=["unread"], limit=20)
        fake_client.get_entries.assert_called_once_with(status=["unread"], limit=20)

        gateway.update_entry(10, content="x")
        fake_client.update_entry.assert_called_once_with(10, content="x")

        gateway.get_feeds()
        fake_client.get_feeds.assert_called_once_with()

        gateway.create_feed(category_id=1, feed_url="http://x/rss")
        fake_client.create_feed.assert_called_once_with(category_id=1, feed_url="http://x/rss")

        gateway.refresh_feed(99)
        fake_client.refresh_feed.assert_called_once_with(99)

    def test_maps_not_found_error(self):
        response = self._response(404, {"error_message": "not found"})
        err = miniflux.ResourceNotFound(response)
        fake_client = Mock()
        fake_client.get_entry.side_effect = err
        with patch("app.infrastructure.miniflux_gateway.miniflux.Client", return_value=fake_client):
            gateway = MinifluxGateway("http://miniflux.local", "api-key")
            with pytest.raises(MinifluxGatewayError) as ctx:
                gateway.get_entry(10)
        assert ctx.value.status_code == 404
        assert "status_code=404" in str(ctx.value)

    def test_maps_client_error(self):
        response = self._response(500, {"error_message": "server error"})
        err = miniflux.ClientError(response)
        fake_client = Mock()
        fake_client.get_entries.side_effect = err
        with patch("app.infrastructure.miniflux_gateway.miniflux.Client", return_value=fake_client):
            gateway = MinifluxGateway("http://miniflux.local", "api-key")
            with pytest.raises(MinifluxGatewayError) as ctx:
                gateway.get_entries(status=["unread"])
        assert ctx.value.status_code == 500
        assert "status_code=500" in str(ctx.value)

    def test_maps_timeout(self):
        fake_client = Mock()
        fake_client.me.side_effect = TimeoutError("timeout")
        with patch("app.infrastructure.miniflux_gateway.miniflux.Client", return_value=fake_client):
            gateway = MinifluxGateway("http://miniflux.local", "api-key")
            with pytest.raises(MinifluxGatewayError) as ctx:
                gateway.me()
        assert "timeout" in str(ctx.value)

class TestLLMGateway:
    @staticmethod
    def _response(status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        return SimpleNamespace(status=status_code, data=body)

    def test_openai_provider_builds_messages_and_respects_max_length(self):
        cfg = SimpleNamespace(
            llm_provider='openai',
            llm_base_url='http://llm.local/v1',
            llm_api_key='k',
            llm_model='m',
            llm_timeout=33,
            llm_max_length=4,
        )
        request_mock = Mock(
            return_value=self._response(
                200,
                {"choices": [{"message": {"content": "ok"}}]},
            )
        )
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            out = gateway.get_result('system prompt', '123456', logger=None)

        assert out == "ok"
        request_mock.assert_called_once()
        args = request_mock.call_args.args
        kwargs = request_mock.call_args.kwargs
        assert args[0] == "POST"
        assert args[1] == "http://llm.local/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer k"
        assert isinstance(kwargs["timeout"], urllib3.Timeout)
        payload = json.loads(kwargs['body'].decode('utf-8'))
        assert payload["model"] == "m"
        assert payload["messages"][0]["content"] == "system prompt"
        assert "1234" in payload["messages"][1]["content"]

    def test_openai_provider_handles_array_content(self):
        cfg = SimpleNamespace(
            llm_provider='openai',
            llm_base_url='http://llm.local',
            llm_api_key='k',
            llm_model='m',
            llm_timeout=30,
            llm_max_length=None,
        )
        request_mock = Mock(
            return_value=self._response(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "hello "},
                                    {"type": "text", "text": "world"},
                                ]
                            }
                        }
                    ]
                },
            )
        )
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            out = gateway.get_result('system prompt', 'input', logger=None)
        assert out == "hello world"

    def test_openai_provider_fallbacks_to_v1_path(self):
        cfg = SimpleNamespace(
            llm_provider='openai',
            llm_base_url='http://llm.local',
            llm_api_key='k',
            llm_model='m',
            llm_timeout=30,
            llm_max_length=None,
        )
        request_mock = Mock(
            side_effect=[
                self._response(404, {"error": "not found"}),
                self._response(200, {"choices": [{"message": {"content": "ok-v1"}}]}),
            ]
        )
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            out = gateway.get_result('system prompt', 'input', logger=None)
        assert out == "ok-v1"
        assert request_mock.call_count == 2
        first_url = request_mock.call_args_list[0].args[1]
        second_url = request_mock.call_args_list[1].args[1]
        assert first_url == "http://llm.local/chat/completions"
        assert second_url == "http://llm.local/v1/chat/completions"

    def test_openai_provider_non_2xx_raises_runtime_error(self):
        cfg = SimpleNamespace(
            llm_provider='openai',
            llm_base_url='http://llm.local',
            llm_api_key='k',
            llm_model='m',
            llm_timeout=30,
            llm_max_length=None,
        )
        request_mock = Mock(return_value=self._response(401, {"error": "unauthorized"}))
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            with pytest.raises(RuntimeError) as ctx:
                gateway.get_result("system prompt", "input", logger=None)
        assert "OpenAI HTTP error status=401" in str(ctx.value)

    def test_gemini_provider_uses_generate_content_http(self):
        cfg = SimpleNamespace(
            llm_provider='gemini',
            llm_base_url='http://gemini.local',
            llm_api_key='k',
            llm_model='gemini-test',
            llm_timeout=30,
            llm_max_length=None,
        )
        request_mock = Mock(
            return_value=self._response(
                200,
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "gemini-ok"}]}}
                    ]
                },
            )
        )
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            out = gateway.get_result('${content}', 'hello', logger=None)

        assert out == "gemini-ok"
        request_mock.assert_called_once()
        args = request_mock.call_args.args
        kwargs = request_mock.call_args.kwargs
        assert args[1] == "http://gemini.local/v1beta/models/gemini-test:generateContent"
        assert kwargs["headers"]["x-goog-api-key"] == "k"
        payload = json.loads(kwargs["body"].decode("utf-8"))
        assert payload["systemInstruction"] == {
            "parts": [{"text": "You are a helpful assistant."}]
        }
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]

    def test_gemini_provider_parse_error_raises_runtime_error(self):
        cfg = SimpleNamespace(
            llm_provider='gemini',
            llm_base_url='http://gemini.local',
            llm_api_key='k',
            llm_model='gemini-test',
            llm_timeout=30,
            llm_max_length=None,
        )
        request_mock = Mock(return_value=self._response(200, {"candidates": [{}]}))
        with patch('app.infrastructure.llm_gateway.urllib3.PoolManager') as pool_ctor:
            pool_ctor.return_value = SimpleNamespace(request=request_mock)
            gateway = LLMGateway(cfg)
            with pytest.raises(RuntimeError) as ctx:
                gateway.get_result("system prompt", "hello", logger=None)
        assert "Gemini response parse error" in str(ctx.value)
