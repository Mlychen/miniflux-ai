from dataclasses import dataclass
from typing import Any, Callable

from adapters.protocols import LLMGatewayProtocol, MinifluxGatewayProtocol
from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository


@dataclass(frozen=True)
class AppServices:
    config: Any
    miniflux_client: MinifluxGatewayProtocol
    llm_client: LLMGatewayProtocol
    logger: Any
    entry_processor: Callable[..., Any]
    entries_repository: EntriesRepository
    ai_news_repository: AiNewsRepository


def get_app_services(app) -> AppServices:
    return app.config['APP_SERVICES']
