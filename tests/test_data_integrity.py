import json
import threading
import unittest
from pathlib import Path

from common.config import Config
from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
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

    def update_entry(self, entry_id, content):
        self.updated.append((entry_id, content))

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
        entries_repository = EntriesRepository(path=str(entries_file), lock=threading.Lock())
        process_entry(
            client,
            entry,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
            entries_repository=entries_repository,
        )

        saved = json.loads(entries_file.read_text(encoding="utf-8"))
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
        self.assertIn("original content", client.updated[0][1])
        self.assertEqual(len(llm_gateway.calls), 2)

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

        llm_gateway = DummyLLMGateway(["should-not-run"])
        entries_repository = EntriesRepository(path=str(entries_file), lock=threading.Lock())
        process_entry(
            client,
            entry,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "error": lambda *a, **k: None})(),
            entries_repository=entries_repository,
        )

        saved = json.loads(entries_file.read_text(encoding="utf-8"))
        self.assertEqual(saved, [])
        self.assertEqual(client.updated, [])
        self.assertEqual(len(llm_gateway.calls), 0)

    def test_generate_daily_news_writes_output_and_clears_entries(self):
        entries_file = TMP_DIR / "daily_entries.json"
        ai_news_file = TMP_DIR / "daily_ai_news.json"
        entries_file.write_text(
            json.dumps(
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

        llm_gateway = DummyLLMGateway(["hello", "block", "sum"])
        entries_repository = EntriesRepository(path=str(entries_file))
        ai_news_repository = AiNewsRepository(path=str(ai_news_file))
        generate_daily_news(
            client,
            config,
            llm_client=llm_gateway,
            logger=type("L", (), {"info": lambda *a, **k: None, "debug": lambda *a, **k: None, "error": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            ai_news_repository=ai_news_repository,
            entries_repository=entries_repository,
        )

        result = json.loads(ai_news_file.read_text(encoding="utf-8"))
        self.assertIn("hello", result)
        self.assertIn("sum", result)
        self.assertIn("block", result)
        self.assertEqual(json.loads(entries_file.read_text(encoding="utf-8")), [])
        self.assertEqual(client.refreshed, [77])
        self.assertEqual(len(llm_gateway.calls), 3)

    def test_generate_daily_news_builds_grouped_summary_block(self):
        entries_file = TMP_DIR / "grouped_entries.json"
        ai_news_file = TMP_DIR / "grouped_ai_news.json"
        entries_file.write_text(
            json.dumps(
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
        llm_gateway = DummyLLMGateway(["hello", "block", "sum"])
        entries_repository = EntriesRepository(path=str(entries_file))
        ai_news_repository = AiNewsRepository(path=str(ai_news_file))
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
        self.assertIn("OpenAI launch", summary_block_input)
        self.assertIn("summary-1", summary_block_input)
        self.assertIn("OpenAI update", summary_block_input)
        self.assertIn("summary-2", summary_block_input)
        self.assertIn("Market move", summary_block_input)
        self.assertIn("summary-3", summary_block_input)
        self.assertNotIn("summary-dup", summary_block_input)

        self.assertLess(
            summary_block_input.index("OpenAI launch"),
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
        entries_file = TMP_DIR / "greeting_entries.json"
        ai_news_file = TMP_DIR / "greeting_ai_news.json"
        entries_file.write_text(
            json.dumps(
                [
                    {
                        "id": "a1",
                        "datetime": "2026-02-25T00:00:00Z",
                        "category": "News",
                        "title": "t1",
                        "content": "item-a",
                        "url": "https://example.com/a",
                    }
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
        llm_gateway = DummyLLMGateway(
            [RuntimeError("g1"), RuntimeError("g2"), RuntimeError("g3"), "block", "sum"]
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
            ai_news_repository=AiNewsRepository(path=str(ai_news_file)),
            entries_repository=EntriesRepository(path=str(entries_file)),
        )

        result = json.loads(ai_news_file.read_text(encoding="utf-8"))
        self.assertIn("### News", result)
        self.assertIn("### Summary", result)
        self.assertTrue(any("greeting_degraded" in msg for msg in logger.warnings))

    def test_generate_daily_news_summary_block_degraded(self):
        entries_file = TMP_DIR / "sb_entries.json"
        ai_news_file = TMP_DIR / "sb_ai_news.json"
        entries_file.write_text(
            json.dumps(
                [
                    {
                        "id": "a1",
                        "datetime": "2026-02-25T00:00:00Z",
                        "category": "Tech",
                        "title": "t1",
                        "content": "item-a",
                        "url": "https://example.com/a",
                    }
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
        llm_gateway = DummyLLMGateway(
            ["hello", RuntimeError("sb1"), RuntimeError("sb2"), RuntimeError("sb3")]
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
            ai_news_repository=AiNewsRepository(path=str(ai_news_file)),
            entries_repository=EntriesRepository(path=str(entries_file)),
        )

        result = json.loads(ai_news_file.read_text(encoding="utf-8"))
        self.assertIn("### News", result)
        self.assertNotIn("### Summary", result)
        self.assertIn("【Tech】", result)
        self.assertTrue(any("summary_block_degraded" in msg for msg in logger.warnings))

    def test_generate_daily_news_summary_degraded(self):
        entries_file = TMP_DIR / "summary_entries.json"
        ai_news_file = TMP_DIR / "summary_ai_news.json"
        entries_file.write_text(
            json.dumps(
                [
                    {
                        "id": "a1",
                        "datetime": "2026-02-25T00:00:00Z",
                        "category": "News",
                        "title": "t1",
                        "content": "item-a",
                        "url": "https://example.com/a",
                    }
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
        llm_gateway = DummyLLMGateway(
            ["hello", "block", RuntimeError("s1"), RuntimeError("s2"), RuntimeError("s3")]
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
            ai_news_repository=AiNewsRepository(path=str(ai_news_file)),
            entries_repository=EntriesRepository(path=str(entries_file)),
        )

        result = json.loads(ai_news_file.read_text(encoding="utf-8"))
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

    def test_processed_news_ids_marks_and_sees(self):
        ids = InMemoryProcessedNewsIds()
        self.assertFalse(ids.seen("x"))
        ids.mark("x")
        self.assertTrue(ids.seen("x"))

    def test_entry_processor_dedups_by_canonical_id(self):
        entries_file = TMP_DIR / "entries_dedup.json"
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
        entries_repository = EntriesRepository(path=str(entries_file), lock=threading.Lock())
        processed_news_ids = InMemoryProcessedNewsIds()
        entry_processor = build_rate_limited_processor(
            config,
            entries_repository=entries_repository,
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
        entry_processor(client, entry_dupe, llm_gateway, logger)

        saved = json.loads(entries_file.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(llm_gateway.calls), 2)


if __name__ == "__main__":
    unittest.main()
