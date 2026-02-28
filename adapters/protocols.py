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


# Alias for backwards compatibility
LLMClientProtocol = LLMGatewayProtocol

# Alias for backwards compatibility
LLMClientProtocol = LLMGatewayProtocol


class LLMRequestPoolProtocol(Protocol):
    def call(
        self,
        prompt: str,
        request: str,
        *,
        logger: Any = None,
        entry_key: Optional[str] = None,
        expected_retries: Optional[int] = None,
        ttl_seconds: Optional[float] = None,
    ) -> Tuple[Optional[str], Optional[object]]: ...

    def get_result(self, prompt: str, request: str, logger: Any = None, **kwargs: Any) -> str: ...

    def get_state(self, entry_key: str) -> Optional[Dict[str, object]]: ...

    def reset_entry(self, entry_key: str) -> None: ...

    def clear_all(self) -> None: ...

    def get_metrics(self) -> Dict[str, int]: ...

    def get_failed_entries(self, limit: int = 100) -> Dict[str, Dict[str, object]]: ...
