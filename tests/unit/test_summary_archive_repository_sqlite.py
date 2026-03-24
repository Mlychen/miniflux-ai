from pathlib import Path
import threading

from app.infrastructure.summary_archive_repository_sqlite import (
    SummaryArchiveRepositorySQLite,
)


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_summary_archive_repository_sqlite"


class TestSummaryArchiveRepositorySQLite:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_append_snapshot_reads_full_row_and_deduplicates_trace(self):
        repo = SummaryArchiveRepositorySQLite(
            path=str(TMP_DIR / "summary_archive.db"), lock=threading.Lock()
        )
        item = {
            "datetime": "2026-03-24T01:00:00Z",
            "category": "News",
            "title": "Archive Title",
            "content": "Summary body",
            "url": "https://example.com/a",
            "ai_category": "科技",
            "ai_subject": "OpenAI",
            "ai_subject_type": "公司",
            "ai_region": "美国",
            "ai_event_type": "发布",
            "ai_group_hint": "科技 / OpenAI / 美国",
            "ai_confidence": 0.9,
        }
        entry = {
            "id": 123,
            "feed": {"id": 77, "title": "Feed Title"},
        }

        created = repo.append_snapshot(
            canonical_id="canon-1",
            trace_id="trace-1",
            item=item,
            entry=entry,
            feed_id=77,
            feed_title="Feed Title",
            processed_at=1700000000,
        )
        duplicate_created = repo.append_snapshot(
            canonical_id="canon-1",
            trace_id="trace-1",
            item=item,
            entry=entry,
            feed_id=77,
            feed_title="Feed Title",
            processed_at=1700000001,
        )

        rows = repo.get_by_canonical_id("canon-1")
        assert created is True
        assert duplicate_created is False
        assert len(rows) == 1
        assert rows[0]["canonical_id"] == "canon-1"
        assert rows[0]["trace_id"] == "trace-1"
        assert rows[0]["entry_id"] == 123
        assert rows[0]["datetime"] == "2026-03-24T01:00:00Z"
        assert rows[0]["title"] == "Archive Title"
        assert rows[0]["summary_content"] == "Summary body"
        assert rows[0]["feed_id"] == 77
        assert rows[0]["feed_title"] == "Feed Title"
        assert rows[0]["processed_at"] == 1700000000
        assert rows[0]["content_hash"]
        assert rows[0]["archive_version"] == 1

    def test_get_by_canonical_id_keeps_multiple_snapshots(self):
        repo = SummaryArchiveRepositorySQLite(
            path=str(TMP_DIR / "summary_archive_multiple.db"), lock=threading.Lock()
        )
        item = {
            "datetime": "2026-03-24T01:00:00Z",
            "category": "News",
            "title": "Archive Title",
            "content": "Summary body",
            "url": "https://example.com/a",
        }

        repo.append_snapshot(
            canonical_id="canon-1",
            trace_id="trace-1",
            item=item,
            processed_at=1000,
        )
        repo.append_snapshot(
            canonical_id="canon-1",
            trace_id="trace-2",
            item=dict(item, content="Summary body v2"),
            processed_at=2000,
        )

        rows = repo.get_by_canonical_id("canon-1")
        assert len(rows) == 2
        assert rows[0]["trace_id"] == "trace-2"
        assert rows[1]["trace_id"] == "trace-1"

    def test_list_recent_orders_by_processed_at_desc(self):
        repo = SummaryArchiveRepositorySQLite(
            path=str(TMP_DIR / "summary_archive_recent.db"), lock=threading.Lock()
        )
        repo.append_snapshots(
            [
                {
                    "canonical_id": "canon-1",
                    "trace_id": "trace-1",
                    "item": {
                        "title": "Older",
                        "content": "Summary 1",
                        "url": "https://example.com/1",
                    },
                    "processed_at": 1000,
                },
                {
                    "canonical_id": "canon-2",
                    "trace_id": "trace-2",
                    "item": {
                        "title": "Newer",
                        "content": "Summary 2",
                        "url": "https://example.com/2",
                    },
                    "processed_at": 2000,
                },
            ]
        )

        rows = repo.list_recent(limit=10, offset=0)
        assert len(rows) == 2
        assert rows[0]["canonical_id"] == "canon-2"
        assert rows[1]["canonical_id"] == "canon-1"
