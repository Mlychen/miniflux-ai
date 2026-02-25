import concurrent.futures
from dataclasses import dataclass
import threading
import time
import traceback

import schedule

from adapters import LLMGateway, MinifluxGateway
from adapters.protocols import LLMGatewayProtocol, MinifluxGatewayProtocol
from common.ai_news_repository import AiNewsRepository
from common.config import Config
from common.entries_repository import EntriesRepository
from common.logger import get_logger
from core.ai_news_helpers import has_ai_news_feed
from core.fetch_unread_entries import fetch_unread_entries
from core.generate_daily_news import generate_daily_news
from core.process_entries import build_rate_limited_processor
from myapp import create_app


@dataclass(frozen=True)
class RuntimeServices:
    config: Config
    logger: object
    miniflux_client: MinifluxGatewayProtocol
    llm_client: LLMGatewayProtocol
    entry_processor: object
    entries_repository: EntriesRepository
    ai_news_repository: AiNewsRepository


def wait_for_miniflux(miniflux_client, logger):
    while True:
        try:
            miniflux_client.me()
            logger.info('Successfully connected to Miniflux!')
            return
        except Exception as e:
            logger.error('Cannot connect to Miniflux: %s' % e)
            time.sleep(3)


def my_schedule(services):
    config = services.config
    logger = services.logger
    miniflux_client = services.miniflux_client
    llm_client = services.llm_client
    entry_processor = services.entry_processor
    entries_repository = services.entries_repository
    ai_news_repository = services.ai_news_repository

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
                miniflux_client.create_feed(category_id=1, feed_url=config.ai_news_url + '/rss/ai-news')
                logger.info('Successfully created the ai_news feed in Miniflux!')
            except Exception as e:
                logger.error('Failed to create the ai_news feed in Miniflux: %s' % e)

        for ai_schedule in config.ai_news_schedule:
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

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"An error occurred in the schedule loop: {e}")
            logger.error(traceback.format_exc())
            time.sleep(30)


def my_flask(services):
    logger = services.logger
    app = create_app(
        config=services.config,
        miniflux_client=services.miniflux_client,
        llm_client=services.llm_client,
        logger=services.logger,
        entry_processor=services.entry_processor,
        entries_repository=services.entries_repository,
        ai_news_repository=services.ai_news_repository,
    )
    logger.info('Starting API')
    app.run(host='0.0.0.0', port=80)


def bootstrap(config_path='config.yml'):
    config = Config.from_file(config_path)
    logger = get_logger(config.log_level)
    file_lock = threading.Lock()
    miniflux_client = MinifluxGateway(config.miniflux_base_url, config.miniflux_api_key)
    llm_client = LLMGateway(config)
    entries_file = 'entries.json'
    entries_repository = EntriesRepository(path=entries_file, lock=file_lock)
    entry_processor = build_rate_limited_processor(config, entries_repository=entries_repository)
    ai_news_file = 'ai_news.json'
    ai_news_repository = AiNewsRepository(path=ai_news_file, lock=file_lock)

    return RuntimeServices(
        config=config,
        logger=logger,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        entry_processor=entry_processor,
        entries_repository=entries_repository,
        ai_news_repository=ai_news_repository,
    )


if __name__ == '__main__':
    services = bootstrap()
    wait_for_miniflux(services.miniflux_client, services.logger)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        if services.config.ai_news_schedule or services.config.miniflux_webhook_secret:
            executor.submit(my_flask, services)
        executor.submit(my_schedule, services)
