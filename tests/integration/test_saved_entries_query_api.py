from pathlib import Path

from app.infrastructure.config import Config
from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite
from app.interfaces.http import create_app


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_saved_entries_query_api"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


def make_config():
    return Config.from_dict({"miniflux": {}, "llm": {"max_workers": 1}})


class TestSavedEntriesQueryAPI:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_query_saved_entries_by_title(self):
        sqlite_path = TMP_DIR / "saved_entries_query.db"
        repository = SavedEntriesRepositorySQLite(path=str(sqlite_path))
        repository.upsert_saved_entry(
            canonical_id="canon-1",
            entry={"id": 11, "title": "AI Chips Weekly", "url": "https://example.com/1"},
            feed={"title": "Tech"},
            now_ts=1000,
        )
        repository.upsert_saved_entry(
            canonical_id="canon-2",
            entry={"id": 12, "title": "AI Agents Weekly", "url": "https://example.com/2"},
            feed={"title": "Tech"},
            now_ts=1001,
        )

        app = create_app(
            config=make_config(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
            saved_entries_repository=repository,
        )

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/saved-entries?title=ai&match=prefix")

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "ok"
        assert payload["total"] == 2
        assert payload["count"] == 2

    def test_query_saved_entries_requires_title(self):
        app = create_app(
            config=make_config(),
            miniflux_client=object(),
            llm_client=object(),
            logger=DummyLogger(),
            entry_processor=lambda *a, **k: None,
        )

        with app.test_client() as client:
            response = client.get("/miniflux-ai/user/saved-entries")

        assert response.status_code == 400
        assert response.get_json() == {"status": "error", "message": "missing title"}
