import time

from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from core.ai_news_helpers import compose_daily_news_content, find_ai_news_feed_id


def generate_daily_news(
    miniflux_client,
    config,
    llm_client,
    logger,
    ai_news_repository=None,
    entries_repository=None,
):
    logger.info('Generating daily news')
    active_entries_repository = entries_repository or EntriesRepository(path='entries.json')
    entries = active_entries_repository.read_all()
    active_ai_news_repository = ai_news_repository or AiNewsRepository(path='ai_news.json')

    if not entries:
        logger.info('No entries to generate daily news')
        return []

    try:
        contents = '\n'.join([i['content'] for i in entries])
        greeting = llm_client.get_result(
            config.ai_news_prompts['greeting'],
            time.strftime('%B %d, %Y at %I:%M %p'),
            logger,
        )
        summary_block = llm_client.get_result(
            config.ai_news_prompts['summary_block'],
            contents,
            logger,
        )
        summary = llm_client.get_result(
            config.ai_news_prompts['summary'],
            summary_block,
            logger,
        )

        response_content = compose_daily_news_content(greeting, summary, summary_block)
        logger.info('Generated daily news successfully')
        active_ai_news_repository.save_latest(response_content)

        feeds = miniflux_client.get_feeds()
        ai_news_feed_id = find_ai_news_feed_id(feeds)

        if ai_news_feed_id:
            miniflux_client.refresh_feed(ai_news_feed_id)
            logger.debug('Successfully refreshed the ai_news feed in Miniflux!')

    except Exception as e:
        logger.error(f'Error generating daily news: {e}')

    finally:
        try:
            active_entries_repository.clear_all()
            logger.info('Cleared entries.json')
        except Exception as e:
            logger.error(f'Failed to clear entries.json: {e}')
