from typing import Any, Dict, Optional, Protocol, Tuple


class MinifluxGatewayProtocol(Protocol):
    def me(self): ...

    def get_entry(self, entry_id: int): ...

    def get_entries(self, **kwargs): ...

    def update_entry(self, entry_id, **kwargs): ...

    def get_feeds(self): ...

    def create_feed(self, **kwargs): ...

    def refresh_feed(self, feed_id): ...


class LLMGatewayProtocol(Protocol):
    def get_result(self, prompt: str, request: str, logger: Any = None): ...


LLMClientProtocol = LLMGatewayProtocol


class LLMRequestPoolProtocol(Protocol):
    def call(
        self,
        prompt: str,
        request: str,
        *,
        logger: Any = None,
        **kwargs: Any,
    ) -> Tuple[Optional[str], Optional[object]]: ...

    def get_result(self, prompt: str, request: str, logger: Any = None, **kwargs: Any) -> str: ...

    def get_metrics(self) -> Dict[str, int]: ...
