import json
from datetime import datetime
import time
import markdown
from flask import current_app

from feedgen.feed import FeedGenerator

def register_ai_news_routes(app):
    @app.route('/rss/ai-news', methods=['GET'])
    def miniflux_ai_news():
        # Todo 根据需要获取最近时间内的文章，或总结后的列表
        services = current_app.config['APP_SERVICES']
        logger = services['logger']
        ai_news_file = services['ai_news_file']
        try:
            with open(ai_news_file, 'r', encoding='utf-8') as file:
                ai_news = json.load(file)
        except FileNotFoundError:
            ai_news = ''
        except Exception as e:
            logger.error(e)
            ai_news = ''

        # 清空 ai_news.json
        with open(ai_news_file, 'w', encoding='utf-8') as file:
            json.dump('', file, indent=4, ensure_ascii=False)

        fg = FeedGenerator()
        fg.id('https://ai-news.miniflux')
        fg.title('֎Newsᴬᴵ for you')
        fg.subtitle('Powered by miniflux-ai')
        fg.author({'name': 'miniflux-ai'})
        fg.link(href='https://ai-news.miniflux', rel='self')

        fe_welcome = fg.add_entry()
        fe_welcome.id('https://ai-news.miniflux')
        fe_welcome.link(href='https://ai-news.miniflux')
        fe_welcome.title(f"Welcome to Newsᴬᴵ")
        fe_welcome.description(markdown.markdown('Welcome to Newsᴬᴵ'))

        if ai_news:
            fe = fg.add_entry()
            fe.id('https://ai-news.miniflux' + time.strftime('%Y-%m-%d-%H-%M'))
            fe.link(href='https://ai-news.miniflux' + time.strftime('%Y-%m-%d-%H-%M'))
            fe.title(f"{'Morning' if datetime.today().hour < 12 else 'Nightly'} Newsᴬᴵ for you - {time.strftime('%Y-%m-%d')}")
            fe.description(markdown.markdown(ai_news))

        result = fg.rss_str(pretty=True)
        return result
