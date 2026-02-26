import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import current_app

import main
from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from myapp import create_app
from myapp.services import AppServices, get_app_services


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class TestServiceContainers(unittest.TestCase):
    def test_create_app_builds_default_repositories_when_not_injected(self):
        app = create_app(
            config=object(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.app_context():
            services = get_app_services(current_app)

        self.assertEqual(services.entries_repository.path, 'entries.json')
        self.assertEqual(services.ai_news_repository.path, 'ai_news.json')
        self.assertIsNotNone(services.entries_repository.lock)
        self.assertIsNotNone(services.ai_news_repository.lock)
        self.assertIsNot(
            services.entries_repository.lock, services.ai_news_repository.lock
        )

    def test_create_app_stores_typed_app_services(self):
        app_lock = object()
        entries_repo = EntriesRepository(path='entries.json', lock=app_lock)
        ai_news_repo = AiNewsRepository(path='ai_news.json', lock=app_lock)
        app = create_app(
            config=object(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            entries_repository=entries_repo,
            ai_news_repository=ai_news_repo,
        )

        with app.app_context():
            services = get_app_services(current_app)

        self.assertIsInstance(services, AppServices)
        self.assertEqual(services.entries_repository.path, 'entries.json')
        self.assertIs(services.entries_repository.lock, app_lock)
        self.assertEqual(services.ai_news_repository.path, 'ai_news.json')
        self.assertIs(services.ai_news_repository.lock, app_lock)

    def test_create_app_prefers_injected_repositories(self):
        entries_repo = EntriesRepository(path='custom_entries.json', lock=object())
        ai_news_repo = AiNewsRepository(path='custom_ai_news.json', lock=object())
        app = create_app(
            config=object(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            entries_repository=entries_repo,
            ai_news_repository=ai_news_repo,
        )

        with app.app_context():
            services = get_app_services(current_app)

        self.assertIs(services.entries_repository, entries_repo)
        self.assertIs(services.ai_news_repository, ai_news_repo)

    def test_bootstrap_returns_runtime_services(self):
        cfg = SimpleNamespace(
            log_level='INFO',
            miniflux_base_url='http://localhost',
            miniflux_api_key='api-key',
        )

        with patch('main.Config.from_file', return_value=cfg), patch(
            'main.get_logger',
            return_value='logger',
        ), patch('main.MinifluxGateway', return_value='miniflux-client'), patch(
            'main.LLMGateway',
            return_value='llm-client',
        ), patch(
            'main.build_rate_limited_processor',
            return_value='entry-processor',
        ):
            services = main.bootstrap('config.yml')

        self.assertIsInstance(services, main.RuntimeServices)
        self.assertIs(services.config, cfg)
        self.assertEqual(services.logger, 'logger')
        self.assertEqual(services.miniflux_client, 'miniflux-client')
        self.assertEqual(services.llm_client, 'llm-client')
        self.assertEqual(services.entry_processor, 'entry-processor')
        self.assertEqual(services.entries_repository.path, 'entries.json')
        self.assertEqual(services.ai_news_repository.path, 'ai_news.json')
        self.assertIs(services.ai_news_repository.lock, services.entries_repository.lock)
        self.assertIsNotNone(services.entries_repository.lock)


if __name__ == '__main__':
    unittest.main()
