import concurrent.futures
from dataclasses import dataclass
import json
import os
import threading
import time
import traceback

import schedule

from adapters import LLMGateway, MinifluxGateway
from adapters.protocols import LLMClientProtocol, MinifluxGatewayProtocol
from common.ai_news_repository import AiNewsRepository
from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.config import Config
from common.entries_repository import EntriesRepository
from common.entries_repository_sqlite import EntriesRepositorySQLite
from common.logger import get_logger
from core.ai_news_helpers import has_ai_news_feed
from core.fetch_unread_entries import fetch_unread_entries
from core.generate_daily_news import generate_daily_news
from core.llm_pool import LLMRequestPool
from core.process_entries import InMemoryProcessedNewsIds, build_rate_limited_processor
from core.process_entries_batch import process_entries_batch
from core.queue import InMemoryQueueBackend, WebhookQueue
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


def should_use_queue(entry_mode):
    """Determine if webhook queue should be used."""
    return entry_mode == "webhook"


@dataclass(frozen=True)
class RuntimeServices:
    config: Config
    logger: object
    miniflux_client: MinifluxGatewayProtocol
    llm_client: LLMClientProtocol
    entry_processor: object
    entries_repository: EntriesRepository
    ai_news_repository: AiNewsRepository


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


def migrate_json_to_sqlite_if_needed(config, entries_repository, ai_news_repository, logger):
    try:
        from common.entries_repository_sqlite import EntriesRepositorySQLite
        from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
    except Exception:
        return

    if not isinstance(entries_repository, EntriesRepositorySQLite):
        return

    try:
        existing_entries = entries_repository.read_all()
        has_sqlite_entries = bool(existing_entries)
    except Exception:
        has_sqlite_entries = False

    has_ai_news = False
    try:
        with ai_news_repository.db.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM ai_news").fetchone()
            has_ai_news = bool(row and row[0] > 0)
    except Exception:
        has_ai_news = False

    if has_sqlite_entries or has_ai_news:
        return

    entries_json_path = getattr(config, "entries_json_path", "entries.json")
    ai_news_json_path = getattr(config, "ai_news_json_path", "ai_news.json")
    processed_json_path = entries_json_path.replace(".json", "_processed.json")

    def _log(message):
        if logger and hasattr(logger, "info"):
            logger.info(message)

    if os.path.exists(entries_json_path):
        try:
            with open(entries_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        if data:
            try:
                entries_repository.append_summary_items(data)
            except Exception:
                pass
        try:
            os.rename(entries_json_path, entries_json_path + ".bak")
        except OSError:
            pass
        _log(f"migrated entries.json to SQLite, items={len(data)}")

    if os.path.exists(processed_json_path):
        try:
            with open(processed_json_path, "r", encoding="utf-8") as f:
                processed = json.load(f)
        except Exception:
            processed = []
        if isinstance(processed, list):
            for entry_id in processed:
                try:
                    entries_repository.add(str(entry_id))
                except Exception:
                    continue
        try:
            os.rename(processed_json_path, processed_json_path + ".bak")
        except OSError:
            pass
        count = len(processed) if isinstance(processed, list) else 0
        _log(f"migrated processed entries list to SQLite, count={count}")

    if os.path.exists(ai_news_json_path):
        try:
            with open(ai_news_json_path, "r", encoding="utf-8") as f:
                content = json.load(f)
        except Exception:
            content = ""
        text = content if isinstance(content, str) else ""
        if text:
            try:
                ai_news_repository.save_latest(text)
            except Exception:
                pass
        try:
            os.rename(ai_news_json_path, ai_news_json_path + ".bak")
        except OSError:
            pass
        _log("migrated ai_news.json to SQLite")


def create_webhook_processor(services):
    """Create the processor function for webhook queue consumer."""

    def process_task(task):
        """Process a single webhook task from the queue."""
        config = services.config
        logger = services.logger
        miniflux_client = services.miniflux_client
        llm_client = services.llm_client
        entry_processor = services.entry_processor

        batch_entries = task.get("entries", [])
        feed = task.get("feed", {})

        # Convert to list format expected by process_entries_batch
        batch_entries = [dict(entry, feed=feed) for entry in batch_entries]

        try:
            result = process_entries_batch(
                config,
                batch_entries,
                miniflux_client,
                entry_processor,
                llm_client,
                logger,
            )
            if result["failures"] > 0:
                logger.error(
                    f"Webhook batch processing had {result['failures']} failures"
                )
        except Exception as e:
            logger.error(f"Error processing webhook batch: {e}")
            logger.error(traceback.format_exc())

    return process_task


def my_flask(services, entry_mode):
    logger = services.logger

    # Create webhook queue if in webhook mode
    webhook_queue = None
    if should_use_queue(entry_mode):
        queue_backend = InMemoryQueueBackend(
            max_size=services.config.miniflux_webhook_queue_max_size
        )
        webhook_queue = WebhookQueue(
            backend=queue_backend,
            workers=services.config.miniflux_webhook_queue_workers,
        )
        # Start consumer threads
        processor_fn = create_webhook_processor(services)
        webhook_queue.start(processor_fn)
        logger.info(
            f"Started webhook queue with {services.config.miniflux_webhook_queue_workers} workers"
        )

    app = create_app(
        config=services.config,
        miniflux_client=services.miniflux_client,
        llm_client=services.llm_client,
        logger=services.logger,
        entry_processor=services.entry_processor,
        entries_repository=services.entries_repository,
        ai_news_repository=services.ai_news_repository,
        webhook_queue=webhook_queue,
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
        max_concurrent=config.llm_max_workers,
        rpm_limit=config.llm_RPM,
        daily_limit=config.llm_daily_limit,
        capacity=config.llm_pool_capacity,
    )
    storage_backend = getattr(config, "storage_backend", "sqlite")
    sqlite_path = getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")
    shared_lock = threading.Lock()
    if storage_backend == "sqlite":
        entries_repository = EntriesRepositorySQLite(path=sqlite_path, lock=shared_lock)
        ai_news_repository = AiNewsRepositorySQLite(path=sqlite_path, lock=shared_lock)
        migrate_json_to_sqlite_if_needed(config, entries_repository, ai_news_repository, logger)
    else:
        entries_repository = EntriesRepository(path="entries.json", lock=shared_lock)
        ai_news_repository = AiNewsRepository(path="ai_news.json", lock=shared_lock)
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
