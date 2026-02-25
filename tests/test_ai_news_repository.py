import json
import threading
import unittest
from pathlib import Path

from common.ai_news_repository import AiNewsRepository


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_ai_news_repository"


class TestAiNewsRepository(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_save_and_consume_latest(self):
        path = TMP_DIR / "ai_news.json"
        repo = AiNewsRepository(path=str(path), lock=threading.Lock())

        repo.save_latest("hello-news")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), "hello-news")

        consumed = repo.consume_latest()
        self.assertEqual(consumed, "hello-news")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), "")

    def test_consume_latest_handles_missing_file(self):
        path = TMP_DIR / "missing_ai_news.json"
        repo = AiNewsRepository(path=str(path), lock=threading.Lock())

        consumed = repo.consume_latest()
        self.assertEqual(consumed, "")
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), "")


if __name__ == "__main__":
    unittest.main()
