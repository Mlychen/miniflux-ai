import json
import threading
import unittest
from pathlib import Path

from common.entries_repository import EntriesRepository


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_entries_repository"


class TestEntriesRepository(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_append_read_and_clear(self):
        path = TMP_DIR / "entries.json"
        repo = EntriesRepository(path=str(path), lock=threading.Lock())

        repo.append_summary_item({"content": "a"})
        repo.append_summary_item({"content": "b"})
        self.assertEqual(repo.read_all(), [{"content": "a"}, {"content": "b"}])

        repo.clear_all()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])

    def test_read_all_handles_missing_file(self):
        path = TMP_DIR / "missing_entries.json"
        repo = EntriesRepository(path=str(path), lock=threading.Lock())
        self.assertEqual(repo.read_all(), [])

    def test_append_read_with_extended_fields(self):
        path = TMP_DIR / "extended_entries.json"
        repo = EntriesRepository(path=str(path), lock=threading.Lock())
        item = {
            "id": "abc",
            "datetime": "2026-02-25T00:00:00Z",
            "category": "News",
            "title": "title",
            "content": "summary",
            "url": "https://example.com/x",
            "ai_category": "科技",
            "ai_subject": "OpenAI",
            "ai_subject_type": "公司",
            "ai_region": "美国",
            "ai_event_type": "产品与发布",
            "ai_group_hint": "科技 / OpenAI / 美国",
            "ai_confidence": 0.9,
        }
        repo.append_summary_item(item)
        self.assertEqual(repo.read_all(), [item])

        repo.clear_all()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
