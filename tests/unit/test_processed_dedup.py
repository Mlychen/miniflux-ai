from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.process_entries import make_canonical_id, process_entry


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_processed_repository_checks_canonical_id():
    entry = {
        "id": 4889,
        "url": "https://example.com/a?utm_source=x",
        "title": "Hello",
        "content": "c",
    }
    canonical_id = make_canonical_id(entry["url"], entry["title"])
    processed_repo = MagicMock()
    processed_repo.contains.return_value = True
    cfg = SimpleNamespace(miniflux_dedup_marker=None, agents={})

    with patch("core.process_entries.trace_logger", MagicMock()):
        process_entry(
            miniflux_client=MagicMock(),
            entry=entry,
            config=cfg,
            llm_client=MagicMock(),
            logger=DummyLogger(),
            entries_repository=MagicMock(),
            processed_entries_repository=processed_repo,
        )

    processed_repo.contains.assert_called_once_with(canonical_id)
