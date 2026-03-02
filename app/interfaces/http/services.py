from dataclasses import dataclass
from typing import Any, Callable

from app.infrastructure.protocols import LLMGatewayProtocol, MinifluxGatewayProtocol


@dataclass(frozen=True)
class AppServices:
    config: Any
    miniflux_client: MinifluxGatewayProtocol
    llm_client: LLMGatewayProtocol
    logger: Any
    entry_processor: Callable[..., Any]
    entries_repository: Any
    ai_news_repository: Any
    task_store: Any = None


def get_app_services(app) -> AppServices:
    return app.config['APP_SERVICES']
