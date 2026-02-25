# Live Checklist

1. `uv run python -c "from main import bootstrap; s=bootstrap('config.yml'); print('bootstrap ok')"`
2. `uv run python -c "import miniflux; from common.config import Config; c=Config.from_file('config.yml'); cli=miniflux.Client(c.miniflux_base_url, api_key=c.miniflux_api_key); print(cli.me().get('username'))"`
3. Validate webhook invalid signature -> 403.
4. Validate webhook valid signature -> 200.
5. Run one polling cycle:
   - `uv run python -c "from main import bootstrap; from core.fetch_unread_entries import fetch_unread_entries; s=bootstrap('config.yml'); fetch_unread_entries(s['config'], s['miniflux_client'], s['entry_processor'], s['llm_client'], s['logger'], s['entries_file'], s['file_lock'])"`
6. Run daily news generation and rss check:
   - `uv run python -c "from main import bootstrap; from core.generate_daily_news import generate_daily_news; s=bootstrap('config.yml'); generate_daily_news(s['miniflux_client'], s['config'], s['llm_client'], s['logger'], s['entries_file'], s['ai_news_file'])"`

