from importlib import import_module
from typing import Any

__all__ = ["LLMGateway", "MinifluxGateway", "LLMGatewayProtocol", "MinifluxGatewayProtocol"]


def __getattr__(name: str) -> Any:
    if name == "LLMGateway":
        return import_module("adapters.llm_gateway").LLMGateway
    if name == "MinifluxGateway":
        return import_module("adapters.miniflux_gateway").MinifluxGateway
    if name == "LLMGatewayProtocol":
        return import_module("adapters.protocols").LLMGatewayProtocol
    if name == "MinifluxGatewayProtocol":
        return import_module("adapters.protocols").MinifluxGatewayProtocol
    raise AttributeError(name)
