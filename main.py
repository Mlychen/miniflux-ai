import concurrent.futures
from dataclasses import dataclass
import threading
import time
import traceback

import schedule

from adapters import LLMGateway, MinifluxGateway
from adapters.protocols import LLMClientProtocol, MinifluxGatewayProtocol
from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.config import Config
from common.entries_repository_sqlite import EntriesRepositorySQLite
from common.logger import get_logger
from common.task_store_sqlite import TaskStoreSQLite
from core.ai_news_helpers import has_ai_news_feed
from core.fetch_unread_entries import fetch_unread_entries
from core.generate_daily_news import generate_daily_news
from core.llm_pool import LLMRequestPool
from core.process_entries import InMemoryProcessedNewsIds, build_rate_limited_processor
from core.process_entries_batch import process_entries_batch
from core.task_worker import PermanentTaskError, TaskWorker
from myapp import create_app


def resolve_entry_mode(config):
    """Resolve final entry mode based on config and webhook_secret."""
    entry_mode = config.miniflux_entry_mode
    webhook_secret = config.miniflux_webhook_secret

    if entry_mode == "auto":
        # auto: use webhook if webhook_secret exists, otherwise polling
        return "webhook" if webhook_secret else "polling"

    if entry_mode == "webhook":
        if not webhook_secret:
            raise ValueError(
                "entry_mode='webhook' requires webhook_secret to be configured"
            )
        return "webhook"

    if entry_mode == "polling":
        return "polling"

    raise ValueError(
        f"Invalid entry_mode: {entry_mode}. Must be one of: auto, webhook, polling"
    )


def should_start_flask(entry_mode, config):
    """Determine if Flask (webhook) should be started."""
    if entry_mode == "webhook":
        return True
    # Also start Flask if ai_news_schedule is configured (for RSS feed access)
    if config.ai_news_schedule:
        return True
    if getattr(config, "debug_enabled", False):
        return True
    return False


def should_start_polling(entry_mode):
    """Determine if polling should be started."""
    return entry_mode == "polling"


@dataclass(frozen=True)
class RuntimeServices:
    config: Config
    logger: object
    miniflux_client: MinifluxGatewayProtocol
    llm_client: LLMClientProtocol
    entry_processor: object
    entries_repository: object
    ai_news_repository: object
    task_store: object = None


def wait_for_miniflux(miniflux_client, logger):
    while True:
        try:
            miniflux_client.me()
            logger.info("Successfully connected to Miniflux!")
            return
        except Exception as e:
            logger.error("Cannot connect to Miniflux: %s" % e)
            time.sleep(3)


def my_schedule(services, entry_mode):
    config = services.config
    logger = services.logger
    miniflux_client = services.miniflux_client
    llm_client = services.llm_client
    entry_processor = services.entry_processor
    entries_repository = services.entries_repository
    ai_news_repository = services.ai_news_repository

    if entry_mode == "polling":
        if config.miniflux_schedule_interval:
            interval = config.miniflux_schedule_interval
        else:
            interval = 15 if config.miniflux_webhook_secret else 1

        schedule.every(interval).minutes.do(
            fetch_unread_entries,
            config,
            miniflux_client,
            entry_processor,
            llm_client,
            logger,
        )
        schedule.run_all()

    if config.ai_news_schedule:
        feeds = miniflux_client.get_feeds()
        if not has_ai_news_feed(feeds):
            try:
                miniflux_client.create_feed(
                    category_id=1,
                    feed_url=config.ai_news_url + "/miniflux-ai/rss/ai-news",
                )
                logger.info("Successfully created the ai_news feed in Miniflux!")
            except Exception as e:
                logger.error("Failed to create the ai_news feed in Miniflux: %s" % e)

        for ai_schedule in config.ai_news_schedule:
            try:
                schedule.every().day.at(ai_schedule).do(
                    generate_daily_news,
                    miniflux_client,
                    config,
                    llm_client,
                    logger,
                    ai_news_repository,
                    entries_repository,
                )
                logger.info(f"Successfully added the ai_news schedule: {ai_schedule}")
            except Exception as e:
                logger.error(
                    f"Failed to add the ai_news schedule: {ai_schedule} error={e}"
                )

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"An error occurred in the schedule loop: {e}")
            logger.error(traceback.format_exc())
            time.sleep(30)


def create_task_record_processor(services):
    """Create processor for durable task records."""

    def process_task(task):
        config = services.config
        logger = services.logger
        miniflux_client = services.miniflux_client
        llm_client = services.llm_client
        entry_processor = services.entry_processor

        payload = task.payload if hasattr(task, "payload") else {}
        if not isinstance(payload, dict):
            raise PermanentTaskError("invalid payload: payload must be an object")

        entry = payload.get("entry")
        feed = payload.get("feed")
        if not isinstance(entry, dict):
            raise PermanentTaskError("invalid payload: missing entry")
        if not isinstance(feed, dict):
            raise PermanentTaskError("invalid payload: missing feed")

        trace_id = str(getattr(task, "trace_id", "") or "")
        entry_data = dict(entry)
        entry_data["feed"] = feed
        if trace_id:
            entry_data["_trace_id"] = trace_id

        result = process_entries_batch(
            config,
            [entry_data],
            miniflux_client,
            entry_processor,
            llm_client,
            logger,
        )
        if result["failures"] > 0:
            raise RuntimeError(
                f"task processing failures={result['failures']} task_id={getattr(task, 'id', 'unknown')}"
            )

    return process_task


def my_flask(services, entry_mode):
    logger = services.logger
    config = services.config

    # Create durable task worker stack if in webhook mode.
    task_store = None
    if entry_mode == "webhook":
        task_store = services.task_store
        if task_store is None:
            raise RuntimeError(
                "Webhook mode requires persistent task store. task_store is not configured."
            )
        task_worker = TaskWorker(
            task_store=task_store,
            workers=getattr(config, "miniflux_task_workers", 2),
            claim_batch_size=getattr(config, "miniflux_task_claim_batch_size", 20),
            lease_seconds=getattr(config, "miniflux_task_lease_seconds", 60),
            poll_interval=getattr(config, "miniflux_task_poll_interval", 1.0),
            retry_delay_seconds=getattr(config, "miniflux_task_retry_delay_seconds", 30),
            logger=logger,
        )
        task_processor_fn = create_task_record_processor(services)
        task_worker.start(task_processor_fn)
        logger.info(
            f"Started persistent task worker with {getattr(config, 'miniflux_task_workers', 2)} workers"
        )

    app = create_app(
        config=services.config,
        miniflux_client=services.miniflux_client,
        llm_client=services.llm_client,
        logger=services.logger,
        entry_processor=services.entry_processor,
        entries_repository=services.entries_repository,
        ai_news_repository=services.ai_news_repository,
        task_store=task_store,
    )
    logger.info("Starting API")
    cfg = services.config
    host = getattr(cfg, "debug_host", "0.0.0.0") or "0.0.0.0"
    port = getattr(cfg, "debug_port", 8081)
    app.run(host=host, port=port)


def bootstrap(config_path="config.yml"):
    config = Config.from_file(config_path)
    logger = get_logger(config.log_level)
    miniflux_client = MinifluxGateway(config.miniflux_base_url, config.miniflux_api_key)
    llm_gateway = LLMGateway(config)
    llm_client = LLMRequestPool(
        llm_gateway=llm_gateway,
        max_concurrent=getattr(config, "llm_max_workers", 4),
        rpm_limit=getattr(config, "llm_RPM", 1000),
        daily_limit=getattr(config, "llm_daily_limit", None),
        capacity=getattr(config, "llm_pool_capacity", None),
    )
    sqlite_path = getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")
    shared_lock = threading.Lock()
    task_store = TaskStoreSQLite(path=sqlite_path, lock=shared_lock)
    entries_repository = EntriesRepositorySQLite(path=sqlite_path, lock=shared_lock)
    ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path, lock=shared_lock)
    processed_news_ids = InMemoryProcessedNewsIds()
    entry_processor = build_rate_limited_processor(
        config,
        entries_repository=entries_repository,
        processed_entries_repository=entries_repository,
        processed_news_ids=processed_news_ids,
    )

    return RuntimeServices(
        config=config,
        logger=logger,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        entry_processor=entry_processor,
        entries_repository=entries_repository,
        ai_news_repository=ai_news_repository,
        task_store=task_store,
    )


if __name__ == "__main__":
    import sys

    services = bootstrap()

    # Resolve entry mode
    try:
        entry_mode = resolve_entry_mode(services.config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Warn if webhook_secret is configured but entry_mode is polling
    if entry_mode == "polling" and services.config.miniflux_webhook_secret:
        print(
            "Warning: webhook_secret is configured but entry_mode='polling'. Webhook is disabled.",
            file=sys.stderr,
        )

    logger = services.logger
    logger.info(f"Entry mode: {entry_mode}")

    # Wait for Miniflux connection
    wait_for_miniflux(services.miniflux_client, logger)

    # Start selected entry points based on entry_mode
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        if should_start_flask(entry_mode, services.config):
            executor.submit(my_flask, services, entry_mode)
            logger.info("Starting Flask (webhook) entry")

        if should_start_polling(entry_mode) or services.config.ai_news_schedule:
            executor.submit(my_schedule, services, entry_mode)
            logger.info("Starting scheduler entry")
