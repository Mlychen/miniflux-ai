from importlib import import_module
from typing import Any

__all__ = ["LLMGateway", "MinifluxGateway", "LLMGatewayProtocol", "MinifluxGatewayProtocol"]


def __getattr__(name: str) -> Any:
    if name == "LLMGateway":
        return import_module("app.infrastructure.llm_gateway").LLMGateway
    if name == "MinifluxGateway":
        return import_module("app.infrastructure.miniflux_gateway").MinifluxGateway
    if name == "LLMGatewayProtocol":
        return import_module("app.infrastructure.protocols").LLMGatewayProtocol
    if name == "MinifluxGatewayProtocol":
        return import_module("app.infrastructure.protocols").MinifluxGatewayProtocol
    raise AttributeError(name)
