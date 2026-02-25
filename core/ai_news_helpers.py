AI_NEWS_TITLE_REQUIRED_KEYWORDS = ('News', 'for you')


def is_ai_news_feed_title(title):
    return all(keyword in title for keyword in AI_NEWS_TITLE_REQUIRED_KEYWORDS)


def has_ai_news_feed(feeds):
    return any(is_ai_news_feed_title(item.get('title', '')) for item in feeds)


def find_ai_news_feed_id(feeds):
    for item in feeds:
        if is_ai_news_feed_title(item.get('title', '')):
            return item.get('id')
    return None


def compose_daily_news_content(greeting, summary, summary_block):
    return greeting + '\n\n### Summary\n' + summary + '\n\n### News\n' + summary_block
