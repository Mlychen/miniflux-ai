import json
import unittest
from pathlib import Path

from common.ai_news_repository import AiNewsRepository
from common.config import Config
from common.entries_repository import EntriesRepository
from myapp import create_app


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_ai_news_api"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def make_app(ai_news_file):
    config = Config.from_dict({})
    entries_file = ai_news_file.with_name("entries.json")
    return create_app(
        config,
        miniflux_client=object(),
        llm_client=object(),
        logger=DummyLogger(),
        entry_processor=lambda *a, **k: None,
        entries_repository=EntriesRepository(path=str(entries_file)),
        ai_news_repository=AiNewsRepository(path=str(ai_news_file)),
    )


class TestAiNewsAPI(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_get_rss_handles_missing_file_and_clears_state(self):
        ai_news_file = TMP_DIR / "missing_ai_news.json"
        app = make_app(ai_news_file)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        self.assertEqual(response.status_code, 200)
        xml = response.data.decode("utf-8")
        self.assertIn("<rss", xml.lower())
        self.assertIn("Powered by miniflux-ai", xml)
        self.assertIn("Welcome to News", xml)
        self.assertTrue(ai_news_file.exists())
        self.assertEqual(json.loads(ai_news_file.read_text(encoding="utf-8")), "")

    def test_get_rss_includes_ai_news_content_and_then_clears_file(self):
        ai_news_file = TMP_DIR / "ai_news.json"
        ai_news_file.write_text(
            json.dumps("### Test Brief\n- item-a", ensure_ascii=False),
            encoding="utf-8",
        )
        app = make_app(ai_news_file)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        self.assertEqual(response.status_code, 200)
        xml = response.data.decode("utf-8")
        self.assertIn("Test Brief", xml)
        self.assertTrue("Morning" in xml or "Nightly" in xml)
        self.assertEqual(json.loads(ai_news_file.read_text(encoding="utf-8")), "")


if __name__ == "__main__":
    unittest.main()
