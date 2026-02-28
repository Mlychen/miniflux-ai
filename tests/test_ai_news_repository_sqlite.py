import unittest
from pathlib import Path

from common.ai_news_repository_sqlite import AiNewsRepositorySQLite


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_ai_news_repository_sqlite"


class TestAiNewsRepositorySQLite(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_save_and_consume_latest(self):
        path = TMP_DIR / "ai_news.db"
        repo = AiNewsRepositorySQLite(path=str(path))

        repo.save_latest("first")
        repo.save_latest("second")
        self.assertEqual(repo.consume_latest(), "second")
        self.assertEqual(repo.consume_latest(), "")


if __name__ == "__main__":
    unittest.main()
