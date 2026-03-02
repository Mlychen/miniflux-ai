from pathlib import Path

from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.config import Config
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.interfaces.http import create_app


TEST_DIR = Path(__file__).resolve().parent
TMP_DIR = TEST_DIR / ".tmp_ai_news_api"


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def make_app(sqlite_path, ai_news_repository=None):
    config = Config.from_dict({})
    if ai_news_repository is None:
        ai_news_repository = AiNewsRepositorySQLite(path=str(sqlite_path))
    return create_app(
        config,
        miniflux_client=object(),
        llm_client=object(),
        logger=DummyLogger(),
        entry_processor=lambda *a, **k: None,
        entries_repository=EntriesRepositorySQLite(path=str(sqlite_path)),
        ai_news_repository=ai_news_repository,
    )


class TestAiNewsAPI:
    def setup_method(self):
        TMP_DIR.mkdir(exist_ok=True)

    def teardown_method(self):
        for p in TMP_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    def test_get_rss_handles_empty_storage_and_keeps_state_empty(self):
        sqlite_path = TMP_DIR / "missing_ai_news.db"
        repo = AiNewsRepositorySQLite(path=str(sqlite_path))
        app = make_app(sqlite_path)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        assert response.status_code == 200
        xml = response.data.decode("utf-8")
        assert "<rss" in xml.lower()
        assert "Powered by miniflux-ai" in xml
        assert "Welcome to News" in xml
        assert sqlite_path.exists()
        assert repo.consume_latest() == ""

    def test_get_rss_includes_ai_news_content_and_then_clears_state(self):
        sqlite_path = TMP_DIR / "ai_news.db"
        repo = AiNewsRepositorySQLite(path=str(sqlite_path))
        repo.save_latest("### Test Brief\n- item-a")
        app = make_app(sqlite_path)

        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        assert response.status_code == 200
        xml = response.data.decode("utf-8")
        assert "Test Brief" in xml
        assert ("Morning" in xml) or ("Nightly" in xml)
        assert repo.consume_latest() == ""

    def test_get_rss_handles_repository_failure(self):
        sqlite_path = TMP_DIR / "ai_news_failing.db"

        class FailingRepository:
            def consume_latest(self):
                raise RuntimeError("broken")

        app = make_app(sqlite_path, ai_news_repository=FailingRepository())
        with app.test_client() as client:
            response = client.get("/miniflux-ai/rss/ai-news")

        assert response.status_code == 200
        xml = response.data.decode("utf-8")
        assert "<rss" in xml.lower()
        assert "Welcome to News" in xml
