from types import SimpleNamespace

import pytest

from app.infrastructure.llm_gateway import LLMGateway


def make_cfg(provider="openai"):
    return SimpleNamespace(
        llm_provider=provider,
        llm_base_url="http://llm.local",
        llm_api_key="k",
        llm_model="m",
        llm_timeout=10,
        llm_max_length=None,
    )


def test_openai_http_error_raises(mocker):
    gateway = LLMGateway(make_cfg())
    mocker.patch.object(gateway, "_post_json", return_value=(500, None, "boom"))
    with pytest.raises(RuntimeError):
        gateway.get_result("prompt", "hello", logger=None)


def test_openai_invalid_json_raises(mocker):
    gateway = LLMGateway(make_cfg())
    mocker.patch.object(gateway, "_post_json", return_value=(200, None, "not-json"))
    with pytest.raises(RuntimeError):
        gateway.get_result("prompt", "hello", logger=None)


def test_gemini_invalid_json_raises(mocker):
    gateway = LLMGateway(make_cfg(provider="gemini"))
    mocker.patch.object(gateway, "_post_json", return_value=(200, None, "not-json"))
    with pytest.raises(RuntimeError):
        gateway.get_result("prompt", "hello", logger=None)
