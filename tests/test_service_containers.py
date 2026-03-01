import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import current_app

import main
from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.entries_repository_sqlite import EntriesRepositorySQLite
from myapp import create_app
from myapp.services import AppServices, get_app_services

TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_service_containers"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class TestServiceContainers(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

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

        self.assertIsInstance(services.entries_repository, EntriesRepositorySQLite)
        self.assertIsInstance(services.ai_news_repository, AiNewsRepositorySQLite)
        self.assertEqual(services.entries_repository.db.path, 'runtime/miniflux_ai.db')
        self.assertEqual(services.ai_news_repository.db.path, 'runtime/miniflux_ai.db')

    def test_create_app_stores_typed_app_services(self):
        app_lock = threading.Lock()
        sqlite_path = TMP_DIR / "test_services_1.db"
        entries_repo = EntriesRepositorySQLite(path=str(sqlite_path), lock=app_lock)
        ai_news_repo = AiNewsRepositorySQLite(path=str(sqlite_path), lock=app_lock)
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
        self.assertEqual(services.entries_repository.db.path, str(sqlite_path))
        self.assertEqual(services.ai_news_repository.db.path, str(sqlite_path))

    def test_create_app_prefers_injected_repositories(self):
        entries_repo = EntriesRepositorySQLite(path=str(TMP_DIR / "test_services_2.db"), lock=threading.Lock())
        ai_news_repo = AiNewsRepositorySQLite(path=str(TMP_DIR / "test_services_2.db"), lock=threading.Lock())
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
            'main.LLMRequestPool',
            return_value='llm-pool',
        ), patch(
            'main.build_rate_limited_processor',
            return_value='entry-processor',
        ):
            services = main.bootstrap('config.yml')

        self.assertIsInstance(services, main.RuntimeServices)
        self.assertIs(services.config, cfg)
        self.assertEqual(services.logger, 'logger')
        self.assertEqual(services.miniflux_client, 'miniflux-client')
        self.assertEqual(services.llm_client, 'llm-pool')
        self.assertEqual(services.entry_processor, 'entry-processor')
        self.assertIsInstance(services.entries_repository, EntriesRepositorySQLite)
        self.assertIsInstance(services.ai_news_repository, AiNewsRepositorySQLite)
        self.assertEqual(services.entries_repository.db.path, 'runtime/miniflux_ai.db')
        self.assertEqual(services.ai_news_repository.db.path, 'runtime/miniflux_ai.db')


if __name__ == '__main__':
    unittest.main()
