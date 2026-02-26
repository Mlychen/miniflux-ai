import threading

from flask import Flask

from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from core.queue import InMemoryQueueBackend, WebhookQueue
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
    shared_lock = (
        getattr(entries_repository, "lock", None)
        or getattr(ai_news_repository, "lock", None)
        or threading.Lock()
    )
    app_entries_repository = entries_repository or EntriesRepository(
        path="entries.json", lock=shared_lock
    )
    app_ai_news_repository = ai_news_repository or AiNewsRepository(
        path="ai_news.json", lock=shared_lock
    )
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

    from myapp.ai_news import register_ai_news_routes
    from myapp.ai_summary import register_ai_summary_routes

    register_ai_news_routes(app)
    register_ai_summary_routes(app)
    return app
