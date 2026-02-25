import miniflux


class MinifluxGateway:
    def __init__(self, base_url, api_key):
        self._client = miniflux.Client(base_url, api_key=api_key)

    def me(self):
        return self._client.me()

    def get_entries(self, **kwargs):
        return self._client.get_entries(**kwargs)

    def update_entry(self, entry_id, **kwargs):
        return self._client.update_entry(entry_id, **kwargs)

    def get_feeds(self):
        return self._client.get_feeds()

    def create_feed(self, **kwargs):
        return self._client.create_feed(**kwargs)

    def refresh_feed(self, feed_id):
        return self._client.refresh_feed(feed_id)
