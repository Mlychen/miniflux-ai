import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from common.config import Config
from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.entries_repository_sqlite import EntriesRepositorySQLite
from core.generate_daily_news import generate_daily_news, safe_llm_call
from core.process_entries import (
    InMemoryProcessedNewsIds,
    build_rate_limited_processor,
    make_canonical_id,
    process_entry,
)


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_integrity"


class DummyMinifluxClient:
    def __init__(self):
        self.updated = []
        self.refreshed = []
        self.feeds = []

    def update_entry(self, entry_id, **kwargs):
        self.updated.append((entry_id, kwargs))

    def get_feeds(self):
        return self.feeds

    def refresh_feed(self, feed_id):
        self.refreshed.append(feed_id)


class DummyLLMGateway:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls = []
        self._lock = threading.Lock()

    def get_result(self, prompt, request, logger=None):
        with self._lock:
            self.calls.append((prompt, request))
            if not self._outputs:
                raise RuntimeError('No more dummy outputs configured')
            result = self._outputs.pop(0)
            if isinstance(result, Exception):
                raise result
            return result


class TestDataIntegrity(unittest.TestCase):
    def setUp(self):
        TMP_DIR.mkdir(exist_ok=True)

    def tearDown(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_process_entry_writes_summary_and_updates_entry(self):
        sqlite_file = TMP_DIR / "entries.db"

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

        llm_gateway = DummyLLMGateway(
            [
                json.dumps(
                    {
                        "summary": "hello-summary",
                        "ai_category": "科技",
                        "subject": "OpenAI",
                        "subject_type": "公司",
                        "region": "美国",
                        "event_type": "产品与发布",
                        "group_hint": "科技 / OpenAI / 美国",
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                ),
                "summary result",
            ]
        )
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file), lock=threading.Lock())
        process_entry(
            client,
            entry,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
            entries_repository=entries_repository,
        )

        saved = entries_repository.read_all()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["content"], "hello-summary")
        self.assertEqual(saved[0]["id"], make_canonical_id(entry["url"], entry["title"]))
        self.assertEqual(saved[0]["ai_category"], "科技")
        self.assertEqual(saved[0]["ai_subject"], "OpenAI")
        self.assertEqual(saved[0]["ai_subject_type"], "公司")
        self.assertEqual(saved[0]["ai_region"], "美国")
        self.assertEqual(saved[0]["ai_event_type"], "产品与发布")
        self.assertEqual(saved[0]["ai_group_hint"], "科技 / OpenAI / 美国")
        self.assertEqual(saved[0]["ai_confidence"], 0.9)
        self.assertEqual(len(client.updated), 1)
        self.assertEqual(client.updated[0][0], 101)
        self.assertIn("original content", client.updated[0][1]["content"])
        self.assertNotIn("summary", client.updated[0][1])
        self.assertEqual(len(llm_gateway.calls), 1)

    def test_process_entry_skips_when_already_processed(self):
        sqlite_file = TMP_DIR / "entries_skip.db"

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

        llm_gateway = DummyLLMGateway(["should-not-run"])
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file), lock=threading.Lock())
        process_entry(
            client,
            entry,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
            entries_repository=entries_repository,
        )

        saved = entries_repository.read_all()
        self.assertEqual(saved, [])
        self.assertEqual(client.updated, [])
        self.assertEqual(len(llm_gateway.calls), 0)

    def test_generate_daily_news_writes_output_and_clears_entries(self):
        sqlite_file = TMP_DIR / "daily.db"

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

        llm_gateway = DummyLLMGateway(["hello", "block", "sum"])
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file))
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_file))
        entries_repository.append_summary_items(
            [
                {
                    "id": "a1",
                    "datetime": "2026-02-25T00:00:00Z",
                    "category": "News",
                    "title": "t1",
                    "content": "item-a",
                    "url": "https://example.com/a",
                },
                {
                    "id": "b1",
                    "datetime": "2026-02-24T00:00:00Z",
                    "category": "News",
                    "title": "t2",
                    "content": "item-b",
                    "url": "https://example.com/b",
                },
            ]
        )
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "debug": lambda *a, **k: None, "error": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        result = ai_news_repository.consume_latest()
        self.assertIn("hello", result)
        self.assertIn("sum", result)
        self.assertIn("block", result)
        self.assertEqual(entries_repository.read_all(), [])
        self.assertEqual(client.refreshed, [77])
        self.assertEqual(len(llm_gateway.calls), 3)

    def test_generate_daily_news_builds_grouped_summary_block(self):
        sqlite_file = TMP_DIR / "grouped.db"

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
        llm_gateway = DummyLLMGateway(["hello", "block", "sum"])
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file))
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_file))
        entries_repository.append_summary_items(
            [
                {
                    "id": "a",
                    "datetime": "2026-02-26T10:00:00Z",
                    "category": "Tech",
                    "title": "OpenAI launch",
                    "content": "summary-1",
                    "url": "https://example.com/openai-launch",
                    "ai_category": "科技",
                    "ai_subject": "OpenAI",
                    "ai_region": "美国",
                    "ai_event_type": "发布",
                },
                {
                    "id": "b",
                    "datetime": "2026-02-25T09:00:00Z",
                    "category": "Tech",
                    "title": "OpenAI update",
                    "content": "summary-2",
                    "url": "https://example.com/openai-update",
                    "ai_category": "科技",
                    "ai_subject": "OpenAI",
                    "ai_region": "美国",
                    "ai_event_type": "更新",
                },
                {
                    "id": "c",
                    "datetime": "2026-02-26T08:00:00Z",
                    "category": "Finance",
                    "title": "Market move",
                    "content": "summary-3",
                    "url": "https://example.com/market-move",
                },
                {
                    "id": "a",
                    "datetime": "2026-02-26T10:00:00Z",
                    "category": "Tech",
                    "title": "OpenAI launch duplicate",
                    "content": "summary-dup",
                    "url": "https://example.com/openai-launch",
                },
            ]
        )
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=type(
                "L",
                (),
                {
                    "info": lambda *a, **k: None,
                    "debug": lambda *a, **k: None,
                    "error": lambda *a, **k: None,
                    "warning": lambda *a, **k: None,
                },
            )(),
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        summary_block_input = llm_gateway.calls[1][1]
        self.assertIn("【Tech / OpenAI】", summary_block_input)
        self.assertIn("【Finance】", summary_block_input)
        self.assertIn("OpenAI launch duplicate", summary_block_input)
        self.assertIn("summary-dup", summary_block_input)
        self.assertNotIn("summary-1", summary_block_input)
        self.assertIn("OpenAI update", summary_block_input)
        self.assertIn("summary-2", summary_block_input)
        self.assertIn("Market move", summary_block_input)
        self.assertIn("summary-3", summary_block_input)

        self.assertGreater(
            summary_block_input.index("OpenAI launch duplicate"),
            summary_block_input.index("OpenAI update"),
        )

    def test_safe_llm_call_retries_and_succeeds(self):
        llm_gateway = DummyLLMGateway(
            [RuntimeError("fail-1"), RuntimeError("fail-2"), "ok"]
        )
        logger = type("L", (), {"error": lambda *a, **k: None})()
        result, err = safe_llm_call(
            "prompt", "text", logger, llm_gateway, retries=2, backoff_seconds=0
        )
        self.assertEqual(result, "ok")
        self.assertIsNone(err)
        self.assertEqual(len(llm_gateway.calls), 3)

    def test_safe_llm_call_returns_none_after_failures(self):
        llm_gateway = DummyLLMGateway(
            [RuntimeError("fail-1"), RuntimeError("fail-2"), RuntimeError("fail-3")]
        )
        logger = type("L", (), {"error": lambda *a, **k: None})()
        result, err = safe_llm_call(
            "prompt", "text", logger, llm_gateway, retries=2, backoff_seconds=0
        )
        self.assertIsNone(result)
        self.assertIsNotNone(err)
        self.assertEqual(len(llm_gateway.calls), 3)

    def test_generate_daily_news_greeting_degraded(self):
        sqlite_file = TMP_DIR / "greeting.db"

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
        llm_gateway = DummyLLMGateway(
            [RuntimeError("g1"), RuntimeError("g2"), RuntimeError("g3"), "block", "sum"]
        )
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file))
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_file))
        entries_repository.append_summary_item(
            {
                "id": "a1",
                "datetime": "2026-02-25T00:00:00Z",
                "category": "News",
                "title": "t1",
                "content": "item-a",
                "url": "https://example.com/a",
            }
        )

        class CaptureLogger:
            def __init__(self):
                self.warnings = []

            def info(self, *args, **kwargs):
                return None

            def debug(self, *args, **kwargs):
                return None

            def error(self, *args, **kwargs):
                return None

            def warning(self, message):
                self.warnings.append(message)

        logger = CaptureLogger()
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=logger,
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        result = ai_news_repository.consume_latest()
        self.assertIn("### News", result)
        self.assertIn("### Summary", result)
        self.assertTrue(any("greeting_degraded" in msg for msg in logger.warnings))

    def test_generate_daily_news_summary_block_degraded(self):
        sqlite_file = TMP_DIR / "summary_block.db"

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
        llm_gateway = DummyLLMGateway(
            ["hello", RuntimeError("sb1"), RuntimeError("sb2"), RuntimeError("sb3")]
        )
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file))
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_file))
        entries_repository.append_summary_item(
            {
                "id": "a1",
                "datetime": "2026-02-25T00:00:00Z",
                "category": "Tech",
                "title": "t1",
                "content": "item-a",
                "url": "https://example.com/a",
            }
        )

        class CaptureLogger:
            def __init__(self):
                self.warnings = []

            def info(self, *args, **kwargs):
                return None

            def debug(self, *args, **kwargs):
                return None

            def error(self, *args, **kwargs):
                return None

            def warning(self, message):
                self.warnings.append(message)

        logger = CaptureLogger()
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=logger,
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        result = ai_news_repository.consume_latest()
        self.assertIn("### News", result)
        self.assertNotIn("### Summary", result)
        self.assertIn("【Tech】", result)
        self.assertTrue(any("summary_block_degraded" in msg for msg in logger.warnings))

    def test_generate_daily_news_summary_degraded(self):
        sqlite_file = TMP_DIR / "summary.db"

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
        llm_gateway = DummyLLMGateway(
            ["hello", "block", RuntimeError("s1"), RuntimeError("s2"), RuntimeError("s3")]
        )
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file))
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_file))
        entries_repository.append_summary_item(
            {
                "id": "a1",
                "datetime": "2026-02-25T00:00:00Z",
                "category": "News",
                "title": "t1",
                "content": "item-a",
                "url": "https://example.com/a",
            }
        )

        class CaptureLogger:
            def __init__(self):
                self.warnings = []

            def info(self, *args, **kwargs):
                return None

            def debug(self, *args, **kwargs):
                return None

            def error(self, *args, **kwargs):
                return None

            def warning(self, message):
                self.warnings.append(message)

        logger = CaptureLogger()
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=logger,
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        result = ai_news_repository.consume_latest()
        self.assertIn("### News", result)
        self.assertNotIn("### Summary", result)
        self.assertTrue(any("summary_degraded" in msg for msg in logger.warnings))

    def test_make_canonical_id_normalizes_url_and_title(self):
        id_a = make_canonical_id("HTTPS://Example.com/path/", "  hello   world ")
        id_b = make_canonical_id("https://example.com/path", "hello world")
        self.assertEqual(id_a, id_b)

    def test_make_canonical_id_handles_missing_url(self):
        id_a = make_canonical_id(None, "Title")
        id_b = make_canonical_id("", "Title")
        self.assertEqual(id_a, id_b)
        self.assertTrue(id_a)

    def test_processed_news_ids_try_mark(self):
        ids = InMemoryProcessedNewsIds()
        self.assertTrue(ids.try_mark("x"))
        self.assertFalse(ids.try_mark("x"))

    def test_processed_news_ids_try_mark_is_atomic(self):
        ids = InMemoryProcessedNewsIds()
        results = []
        results_lock = threading.Lock()

        def worker():
            marked = ids.try_mark("same-id")
            with results_lock:
                results.append(marked)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 20)
        self.assertEqual(sum(1 for marked in results if marked), 1)
        self.assertFalse(ids.try_mark("same-id"))

    def test_entry_processor_dedups_by_persistent_processed_repository(self):
        sqlite_file = TMP_DIR / "entries_dedup.db"

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
        llm_gateway = DummyLLMGateway(
            [
                json.dumps(
                    {
                        "summary": "summary result",
                        "ai_category": "科技",
                        "subject": "OpenAI",
                        "subject_type": "公司",
                        "region": "美国",
                        "event_type": "产品与发布",
                        "group_hint": "科技 / OpenAI / 美国",
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                ),
                "summary result",
            ]
        )
        entries_repository = EntriesRepositorySQLite(path=str(sqlite_file), lock=threading.Lock())
        processed_news_ids = InMemoryProcessedNewsIds()
        entry_processor = build_rate_limited_processor(
            config,
            entries_repository=entries_repository,
            processed_entries_repository=entries_repository,
            processed_news_ids=processed_news_ids,
        )
        logger = type(
            "L",
            (),
            {
                "info": lambda *a, **k: None,
                "error": lambda *a, **k: None,
                "debug": lambda *a, **k: None,
            },
        )()
        entry = {
            "id": 201,
            "created_at": "2026-02-25T00:00:00Z",
            "title": "t3",
            "url": "https://example.com/c/",
            "content": "original content",
            "feed": {
                "site_url": "https://example.com",
                "category": {"title": "News"},
            },
        }
        entry_dupe = dict(entry, id=202, url="https://example.com/c")

        entry_processor(client, entry, llm_gateway, logger)
        with patch("core.process_entries._trace_log") as trace_log:
            entry_dupe["_trace_id"] = "trace-dedup-1"
            entry_processor(client, entry_dupe, llm_gateway, logger)

        saved = entries_repository.read_all()
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(llm_gateway.calls), 1)
        trace_log.assert_any_call(
            "trace-dedup-1",
            "202",
            "dedup",
            "check",
            status="skipped",
            data={
                "reason": "processed_repository_found",
                "canonical_id": make_canonical_id(entry_dupe["url"], entry_dupe["title"]),
            },
        )
        trace_log.assert_any_call(
            "trace-dedup-1",
            "202",
            "process",
            "complete",
            status="skipped",
            duration_ms=unittest.mock.ANY,
            data={
                "canonical_id": make_canonical_id(entry_dupe["url"], entry_dupe["title"]),
                "agents_processed": 0,
                "agent_details": [],
                "reason": "processed_repository_found",
            },
        )


if __name__ == "__main__":
    unittest.main()
