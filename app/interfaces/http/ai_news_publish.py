from datetime import datetime
import time

import markdown
from flask import current_app
from feedgen.feed import FeedGenerator

from app.interfaces.http.services import get_app_services


def register_ai_news_publish_routes(app):
    @app.route('/miniflux-ai/rss/ai-news', methods=['GET'])
    def miniflux_ai_news():
        # TODO: support selecting articles in a configurable recent time window.
        services = get_app_services(current_app)
        logger = services.logger
        ai_news_repository = services.ai_news_repository

        try:
            ai_news = ai_news_repository.consume_latest()
        except Exception as e:
            logger.error(e)
            ai_news = ''

        fg = FeedGenerator()
        fg.id('https://ai-news.miniflux')
        fg.title('News for you')
        fg.subtitle('Powered by miniflux-ai')
        fg.author({'name': 'miniflux-ai'})
        fg.link(href='https://ai-news.miniflux', rel='self')

        fe_welcome = fg.add_entry()
        fe_welcome.id('https://ai-news.miniflux')
        fe_welcome.link(href='https://ai-news.miniflux')
        fe_welcome.title('Welcome to News')
        fe_welcome.description(markdown.markdown('Welcome to News'))

        if ai_news:
            fe = fg.add_entry()
            entry_id = 'https://ai-news.miniflux' + time.strftime('%Y-%m-%d-%H-%M')
            fe.id(entry_id)
            fe.link(href=entry_id)
            period = 'Morning' if datetime.today().hour < 12 else 'Nightly'
            fe.title(f'{period} News for you - {time.strftime("%Y-%m-%d")}')
            fe.description(markdown.markdown(ai_news))

        return fg.rss_str(pretty=True)
