from typing import Optional

import miniflux


class MinifluxGatewayError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, reason: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class MinifluxGateway:
    def __init__(self, base_url, api_key):
        self._client = miniflux.Client(base_url, api_key=api_key)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except miniflux.ClientError as e:
            status_code = getattr(e, "status_code", None)
            reason = e.get_error_reason() if hasattr(e, "get_error_reason") else ""
            raise MinifluxGatewayError(
                f"Miniflux error status_code={status_code} reason={reason}",
                status_code=status_code,
                reason=reason,
            ) from e
        except Exception as e:
            raise MinifluxGatewayError(f"Miniflux request failed: {e}") from e

    def me(self):
        return self._call(self._client.me)

    def get_entry(self, entry_id: int):
        return self._call(self._client.get_entry, entry_id)

    def get_entries(self, **kwargs):
        return self._call(self._client.get_entries, **kwargs)

    def update_entry(self, entry_id, **kwargs):
        return self._call(self._client.update_entry, entry_id, **kwargs)

    def get_feeds(self):
        return self._call(self._client.get_feeds)

    def create_feed(self, **kwargs):
        return self._call(self._client.create_feed, **kwargs)

    def refresh_feed(self, feed_id):
        return self._call(self._client.refresh_feed, feed_id)
