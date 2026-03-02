from pathlib import Path

from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_entries_repository_sqlite"


class TestEntriesRepositorySQLite:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_append_read_and_clear(self):
        path = TMP_DIR / "entries.db"
        repo = EntriesRepositorySQLite(path=str(path))

        item_a = {
            "id": "a",
            "datetime": "2026-02-25T00:00:00Z",
            "category": "News",
            "title": "title-a",
            "content": "summary-a",
            "url": "https://example.com/a",
            "ai_category": "科技",
            "ai_subject": "OpenAI",
            "ai_subject_type": "公司",
            "ai_region": "美国",
            "ai_event_type": "发布",
            "ai_group_hint": "科技 / OpenAI / 美国",
            "ai_confidence": 0.9,
        }
        item_b = {
            "id": "b",
            "datetime": "2026-02-26T00:00:00Z",
            "category": "News",
            "title": "title-b",
            "content": "summary-b",
            "url": "https://example.com/b",
            "ai_category": "科技",
            "ai_subject": "Google",
            "ai_subject_type": "公司",
            "ai_region": "美国",
            "ai_event_type": "更新",
            "ai_group_hint": "科技 / Google / 美国",
            "ai_confidence": 0.8,
        }

        repo.append_summary_item(item_a)
        repo.append_summary_item(item_b)
        rows = repo.read_all()
        assert len(rows) == 2
        assert rows[0]["id"] == "a"
        assert rows[1]["id"] == "b"

        repo.clear_all()
        assert repo.read_all() == []

    def test_append_summary_items_batch(self):
        path = TMP_DIR / "batch_entries.db"
        repo = EntriesRepositorySQLite(path=str(path))

        items = [
            {
                "id": f"item-{i}",
                "datetime": f"2026-02-{20 + i:02d}T00:00:00Z",
                "category": "News",
                "title": f"title-{i}",
                "content": f"summary-{i}",
                "url": f"https://example.com/{i}",
                "ai_category": "科技",
                "ai_subject": f"Subject{i}",
                "ai_subject_type": "公司",
                "ai_region": "美国",
                "ai_event_type": "发布",
                "ai_group_hint": f"科技 / Subject{i}",
                "ai_confidence": 0.9,
            }
            for i in range(10)
        ]

        repo.append_summary_items(items)
        rows = repo.read_all()
        assert len(rows) == 10
        assert rows[0]["id"] == "item-0"
        assert rows[9]["id"] == "item-9"
