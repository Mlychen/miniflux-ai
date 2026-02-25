import concurrent.futures
import threading
import time
import traceback

import miniflux
import schedule

from common.config import Config
from common.logger import get_logger
from core.fetch_unread_entries import fetch_unread_entries
from core.generate_daily_news import generate_daily_news
from core.get_ai_result import build_llm_client
from core.process_entries import build_rate_limited_processor
from myapp import create_app


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
    config = services['config']
    logger = services['logger']
    miniflux_client = services['miniflux_client']
    llm_client = services['llm_client']
    entry_processor = services['entry_processor']
    entries_file = services['entries_file']
    ai_news_file = services['ai_news_file']
    file_lock = services['file_lock']

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
        entries_file,
        file_lock,
    )
    schedule.run_all()

    if config.ai_news_schedule:
        feeds = miniflux_client.get_feeds()
        if not any('Newsᴬᴵ for you' in item['title'] for item in feeds):
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
                entries_file,
                ai_news_file,
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
    logger = services['logger']
    app = create_app(
        services['config'],
        services['miniflux_client'],
        services['llm_client'],
        services['logger'],
        services['entry_processor'],
        services['entries_file'],
        services['ai_news_file'],
    )
    logger.info('Starting API')
    app.run(host='0.0.0.0', port=80)


def bootstrap(config_path='config.yml'):
    config = Config.from_file(config_path)
    logger = get_logger(config.log_level)
    miniflux_client = miniflux.Client(config.miniflux_base_url, api_key=config.miniflux_api_key)
    llm_client = build_llm_client(config)
    entry_processor = build_rate_limited_processor(config)

    return {
        'config': config,
        'logger': logger,
        'miniflux_client': miniflux_client,
        'llm_client': llm_client,
        'entry_processor': entry_processor,
        'entries_file': 'entries.json',
        'ai_news_file': 'ai_news.json',
        'file_lock': threading.Lock(),
    }


if __name__ == '__main__':
    services = bootstrap()
    wait_for_miniflux(services['miniflux_client'], services['logger'])

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        if services['config'].ai_news_schedule or services['config'].miniflux_webhook_secret:
            executor.submit(my_flask, services)
        executor.submit(my_schedule, services)
