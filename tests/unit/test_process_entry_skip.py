from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.processor import process_entry, _should_preprocess_entry


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_skip_without_preprocess_when_all_agents_filtered():
    entry = {
        "id": 1,
        "url": "https://example.com/post",
        "title": "t",
        "content": "raw content",
        "feed": {"site_url": "https://example.com/post", "category": {"title": "c"}},
        "created_at": "2026-02-28T00:00:00Z",
    }
    cfg = SimpleNamespace(
        miniflux_dedup_marker="DEDUP",
        agents={
            "summary": {
                "title": "AI 摘要：",
                "style_block": True,
                "allow_list": ["https://allowed.example/*"],
                "deny_list": None,
                "prompt": "p",
            }
        },
    )

    with patch("app.domain.processor.trace_logger", MagicMock()), patch(
        "app.domain.processor.preprocess_entry", MagicMock()
    ) as preprocess_mock:
        process_entry(
            miniflux_client=MagicMock(),
            entry=entry,
            config=cfg,
            llm_client=MagicMock(),
            logger=DummyLogger(),
            entries_repository=None,
            processed_entries_repository=None,
        )

    preprocess_mock.assert_not_called()


def test_all_agents_filtered_marks_processed_repository():
    entry = {
        "id": 2,
        "url": "https://example.com/post2",
        "title": "t2",
        "content": "raw content",
        "feed": {"site_url": "https://example.com/post2", "category": {"title": "c"}},
        "created_at": "2026-02-28T00:00:00Z",
    }
    cfg = SimpleNamespace(
        miniflux_dedup_marker="DEDUP",
        agents={
            "summary": {
                "title": "AI 摘要：",
                "style_block": True,
                "allow_list": ["https://allowed.example/*"],
                "deny_list": None,
                "prompt": "p",
            }
        },
    )
    processed_repo = MagicMock()
    processed_repo.contains.return_value = False

    with patch("app.domain.processor.trace_logger", MagicMock()):
        process_entry(
            miniflux_client=MagicMock(),
            entry=entry,
            config=cfg,
            llm_client=MagicMock(),
            logger=DummyLogger(),
            entries_repository=MagicMock(),
            processed_entries_repository=processed_repo,
        )

    processed_repo.add.assert_called_once()


def test_preprocess_not_skipped_for_natural_blockquote_content():
    entry = {
        "id": 3,
        "url": "https://example.com/post3",
        "title": "t3",
        "content": "<blockquote><p>quoted article text</p></blockquote>",
        "feed": {"site_url": "https://example.com/post3", "category": {"title": "c"}},
        "created_at": "2026-02-28T00:00:00Z",
    }
    cfg = SimpleNamespace(
        miniflux_dedup_marker="DEDUP",
        agents={
            "summary": {
                "title": "AI 摘要：",
                "style_block": True,
                "allow_list": None,
                "deny_list": None,
                "prompt": "p",
            }
        },
    )

    assert _should_preprocess_entry(cfg, entry) is True
