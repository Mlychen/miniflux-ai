import unittest

from core.ai_news_helpers import (
    compose_daily_news_content,
    find_ai_news_feed_id,
    has_ai_news_feed,
    is_ai_news_feed_title,
)
from core.entry_rendering import build_summary_entry, render_agent_response


class TestEntryRendering(unittest.TestCase):
    def test_build_summary_entry(self):
        entry = {
            'created_at': '2026-02-25T00:00:00Z',
            'title': 'title',
            'url': 'https://example.com/x',
            'feed': {'category': {'title': 'News'}},
        }
        item = build_summary_entry(entry, 'summary')
        self.assertEqual(
            item,
            {
                'datetime': '2026-02-25T00:00:00Z',
                'category': 'News',
                'title': 'title',
                'content': 'summary',
                'url': 'https://example.com/x',
            },
        )

    def test_render_agent_response_style_block(self):
        out = render_agent_response(
            {'title': 'AI Summary: ', 'style_block': True},
            'line1\nline2',
        )
        self.assertIn('<blockquote>', out)
        self.assertIn('AI Summary:', out)
        self.assertIn('line1line2', out)

    def test_render_agent_response_markdown(self):
        out = render_agent_response(
            {'title': 'AI Translate: ', 'style_block': False},
            '**bold**',
        )
        self.assertTrue(out.startswith('AI Translate: '))
        self.assertIn('<strong>bold</strong>', out)
        self.assertTrue(out.endswith('<hr><br />'))


class TestAiNewsHelpers(unittest.TestCase):
    def test_title_matching_and_feed_discovery(self):
        feeds = [
            {'id': 1, 'title': 'Other feed'},
            {'id': 77, 'title': 'Morning News for you'},
        ]
        self.assertTrue(is_ai_news_feed_title('Morning News for you'))
        self.assertFalse(is_ai_news_feed_title('Morning News'))
        self.assertTrue(has_ai_news_feed(feeds))
        self.assertEqual(find_ai_news_feed_id(feeds), 77)

    def test_compose_daily_news_content(self):
        out = compose_daily_news_content('hello', 'sum', 'block')
        self.assertIn('hello', out)
        self.assertIn('### Summary', out)
        self.assertIn('### News', out)
        self.assertIn('sum', out)
        self.assertIn('block', out)


if __name__ == '__main__':
    unittest.main()
