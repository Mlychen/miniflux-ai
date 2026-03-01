import unittest
from pathlib import Path

from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.config import Config
from common.entries_repository_sqlite import EntriesRepositorySQLite
from myapp import create_app


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_ai_news_api"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def make_app(sqlite_path):
    config = Config.from_dict({})
    return create_app(
        config,
        miniflux_client=object(),
        llm_client=object(),
        logger=DummyLogger(),
        entry_processor=lambda *a, **k: None,
        entries_repository=EntriesRepositorySQLite(path=str(sqlite_path)),
        ai_news_repository=AiNewsRepositorySQLite(path=str(sqlite_path)),
    )


class TestAiNewsAPI(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_get_rss_handles_empty_storage_and_keeps_state_empty(self):
        sqlite_path = TMP_DIR / "missing_ai_news.db"
        repo = AiNewsRepositorySQLite(path=str(sqlite_path))
        app = make_app(sqlite_path)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        self.assertEqual(response.status_code, 200)
        xml = response.data.decode("utf-8")
        self.assertIn("<rss", xml.lower())
        self.assertIn("Powered by miniflux-ai", xml)
        self.assertIn("Welcome to News", xml)
        self.assertTrue(sqlite_path.exists())
        self.assertEqual(repo.consume_latest(), "")

    def test_get_rss_includes_ai_news_content_and_then_clears_state(self):
        sqlite_path = TMP_DIR / "ai_news.db"
        repo = AiNewsRepositorySQLite(path=str(sqlite_path))
        repo.save_latest("### Test Brief\n- item-a")
        app = make_app(sqlite_path)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        self.assertEqual(response.status_code, 200)
        xml = response.data.decode("utf-8")
        self.assertIn("Test Brief", xml)
        self.assertTrue("Morning" in xml or "Nightly" in xml)
        self.assertEqual(repo.consume_latest(), "")


if __name__ == "__main__":
    unittest.main()
