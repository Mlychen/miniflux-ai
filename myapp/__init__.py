from flask import Flask


def create_app(config, miniflux_client, llm_client, logger, entry_processor, entries_file='entries.json', ai_news_file='ai_news.json'):
    app = Flask(__name__)
    app.config['APP_SERVICES'] = {
        'config': config,
        'miniflux_client': miniflux_client,
        'llm_client': llm_client,
        'logger': logger,
        'entry_processor': entry_processor,
        'entries_file': entries_file,
        'ai_news_file': ai_news_file,
    }

    from myapp.ai_news import register_ai_news_routes
    from myapp.ai_summary import register_ai_summary_routes

    register_ai_news_routes(app)
    register_ai_summary_routes(app)
    return app
