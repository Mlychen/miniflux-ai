import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from common.config import Config
from core.generate_daily_news import generate_daily_news
from core.process_entries import process_entry


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_integrity"


class DummyMinifluxClient:
    def __init__(self):
        self.updated = []
        self.refreshed = []
        self.feeds = []

    def update_entry(self, entry_id, content):
        self.updated.append((entry_id, content))

    def get_feeds(self):
        return self.feeds

    def refresh_feed(self, feed_id):
        self.refreshed.append(feed_id)


class TestDataIntegrity(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_process_entry_writes_summary_and_updates_entry(self):
        entries_file = TMP_DIR / "entries.json"
        entries_file.write_text("[]", encoding="utf-8")

        config = Config.from_dict(
            {
                "agents": {
                    "summary": {
                        "title": "AI summary:",
                        "prompt": "summarize",
                        "style_block": True,
                        "allow_list": None,
                        "deny_list": None,
                    }
                }
            }
        )
        client = DummyMinifluxClient()
        entry = {
            "id": 101,
            "created_at": "2026-02-25T00:00:00Z",
            "title": "t",
            "url": "https://example.com/a",
            "content": "original content",
            "feed": {
                "site_url": "https://example.com",
                "category": {"title": "News"},
            },
        }

        with patch("core.process_entries.get_ai_result", return_value="summary result"):
            process_entry(
                client,
                entry,
                config,
                llm_client=object(),
                logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
                entries_file=str(entries_file),
                lock=threading.Lock(),
            )

        saved = json.loads(entries_file.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["content"], "summary result")
        self.assertEqual(len(client.updated), 1)
        self.assertEqual(client.updated[0][0], 101)
        self.assertIn("original content", client.updated[0][1])

    def test_process_entry_skips_when_already_processed(self):
        entries_file = TMP_DIR / "entries_skip.json"
        entries_file.write_text("[]", encoding="utf-8")

        config = Config.from_dict(
            {
                "agents": {
                    "summary": {
                        "title": "AI summary:",
                        "prompt": "summarize",
                        "style_block": False,
                        "allow_list": None,
                        "deny_list": None,
                    }
                }
            }
        )
        client = DummyMinifluxClient()
        entry = {
            "id": 102,
            "created_at": "2026-02-25T00:00:00Z",
            "title": "t2",
            "url": "https://example.com/b",
            "content": "AI summary: existing content",
            "feed": {
                "site_url": "https://example.com",
                "category": {"title": "News"},
            },
        }

        with patch("core.process_entries.get_ai_result", return_value="should-not-run"):
            process_entry(
                client,
                entry,
                config,
                llm_client=object(),
                logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
                entries_file=str(entries_file),
                lock=threading.Lock(),
            )

        saved = json.loads(entries_file.read_text(encoding="utf-8"))
        self.assertEqual(saved, [])
        self.assertEqual(client.updated, [])

    def test_generate_daily_news_writes_output_and_clears_entries(self):
        entries_file = TMP_DIR / "daily_entries.json"
        ai_news_file = TMP_DIR / "daily_ai_news.json"
        entries_file.write_text(
            json.dumps(
                [
                    {"content": "item-a"},
                    {"content": "item-b"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ai_news_file.write_text('""', encoding="utf-8")

        config = Config.from_dict(
            {
                "ai_news": {
                    "prompts": {
                        "greeting": "greeting",
                        "summary_block": "summary_block",
                        "summary": "summary",
                    }
                }
            }
        )
        client = DummyMinifluxClient()
        client.feeds = [{"id": 77, "title": "Newsᴬᴵ for you"}]

        with patch("core.generate_daily_news.get_ai_result", side_effect=["hello", "block", "sum"]):
            generate_daily_news(
                client,
                config,
                llm_client=object(),
                logger=type("L", (), {"info": lambda *a, **k: None, "debug": lambda *a, **k: None, "error": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
                entries_file=str(entries_file),
                ai_news_file=str(ai_news_file),
            )

        result = json.loads(ai_news_file.read_text(encoding="utf-8"))
        self.assertIn("hello", result)
        self.assertIn("sum", result)
        self.assertIn("block", result)
        self.assertEqual(json.loads(entries_file.read_text(encoding="utf-8")), [])
        self.assertEqual(client.refreshed, [77])


if __name__ == "__main__":
    unittest.main()
