import threading

from flask import Flask

from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from myapp.services import AppServices


def create_app(
    config,
    miniflux_client,
    llm_client,
    logger,
    entry_processor,
    entries_repository=None,
    ai_news_repository=None,
    webhook_queue=None,
):
    if entries_repository is None:
        entries_lock = threading.Lock()
        app_entries_repository = EntriesRepository(
            path="entries.json", lock=entries_lock
        )
    else:
        app_entries_repository = entries_repository

    if ai_news_repository is None:
        ai_news_lock = threading.Lock()
        app_ai_news_repository = AiNewsRepository(
            path="ai_news.json", lock=ai_news_lock
        )
    else:
        app_ai_news_repository = ai_news_repository
    app = Flask(__name__)
    app.config["APP_SERVICES"] = AppServices(
        config=config,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        logger=logger,
        entry_processor=entry_processor,
        entries_repository=app_entries_repository,
        ai_news_repository=app_ai_news_repository,
    )

    # Initialize webhook queue if provided (for webhook entry mode)
    if webhook_queue:
        app.config["WEBHOOK_QUEUE"] = webhook_queue

    from myapp.ai_news_publish import register_ai_news_publish_routes
    from myapp.webhook_ingest import register_webhook_routes

    register_ai_news_publish_routes(app)
    register_webhook_routes(app)
    return app
