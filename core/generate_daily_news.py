import json
import time

from core.get_ai_result import get_ai_result

def generate_daily_news(miniflux_client, config, llm_client, logger, entries_file='entries.json', ai_news_file='ai_news.json'):
    logger.info('Generating daily news')
    # fetch entries.json
    try:
        with open(entries_file, 'r', encoding='utf-8') as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning('entries.json not found or corrupted, skipping daily news generation')
        return []

    if not entries:
        logger.info('No entries to generate daily news')
        return []

    try:
        contents = '\n'.join([i['content'] for i in entries])
        # greeting
        greeting = get_ai_result(llm_client, config, config.ai_news_prompts['greeting'], time.strftime('%B %d, %Y at %I:%M %p'), logger)
        # summary_block
        summary_block = get_ai_result(llm_client, config, config.ai_news_prompts['summary_block'], contents, logger)
        # summary
        summary = get_ai_result(llm_client, config, config.ai_news_prompts['summary'], summary_block, logger)

        response_content = greeting + '\n\n### 🌐Summary\n' + summary + '\n\n### 📝News\n' + summary_block

        logger.info('Generated daily news successfully')

        with open(ai_news_file, 'w', encoding='utf-8') as f:
            json.dump(response_content, f, indent=4, ensure_ascii=False)

        # trigger miniflux feed refresh
        feeds = miniflux_client.get_feeds()
        ai_news_feed_id = next((item['id'] for item in feeds if 'Newsᴬᴵ for you' in item['title']), None)

        if ai_news_feed_id:
            miniflux_client.refresh_feed(ai_news_feed_id)
            logger.debug('Successfully refreshed the ai_news feed in Miniflux!')
    
    except Exception as e:
        logger.error(f'Error generating daily news: {e}')
    
    finally:
        try:
            with open(entries_file, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4, ensure_ascii=False)
            logger.info('Cleared entries.json')
        except Exception as e:
            logger.error(f'Failed to clear entries.json: {e}')
