import threading
from types import SimpleNamespace

from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.config import Config
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.interfaces.http import create_app
from app.infrastructure.miniflux_gateway import MinifluxGatewayError


def build_app(tmp_path, miniflux_client):
    config = Config.from_dict({"debug": {"enabled": True}})
    entries_repo = EntriesRepositorySQLite(
        path=str(tmp_path / "entries.db"), lock=threading.Lock()
    )
    ai_repo = AiNewsRepositorySQLite(
        path=str(tmp_path / "ai.db"), lock=threading.Lock()
    )
    app = create_app(
        config,
        miniflux_client=miniflux_client,
        llm_client=SimpleNamespace(),
        logger=None,
        entry_processor=lambda *a, **k: None,
        entries_repository=entries_repo,
        ai_news_repository=ai_repo,
    )
    return app


def test_debug_miniflux_me_ok(tmp_path):
    miniflux_client = SimpleNamespace(me=lambda: {"username": "demo"})
    app = build_app(tmp_path, miniflux_client)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/miniflux/me")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["me"]["username"] == "demo"


def test_debug_miniflux_me_error(tmp_path):
    def raise_error():
        raise MinifluxGatewayError("bad", status_code=500, reason="fail")

    miniflux_client = SimpleNamespace(me=raise_error)
    app = build_app(tmp_path, miniflux_client)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/miniflux/me")
    payload = response.get_json()
    assert response.status_code == 502
    assert payload["status"] == "error"


def test_debug_miniflux_entry_not_found(tmp_path):
    miniflux_client = SimpleNamespace(get_entry=lambda _entry_id: None)
    app = build_app(tmp_path, miniflux_client)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/miniflux/entry/10")
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["message"] == "entry not found"


def test_debug_miniflux_entry_ok(tmp_path):
    miniflux_client = SimpleNamespace(
        get_entry=lambda _entry_id: {
            "id": 10,
            "status": "read",
            "title": "hello",
            "url": "https://example.com/10",
            "feed_id": 1,
            "published_at": "2026-02-25T00:00:00Z",
            "created_at": "2026-02-25T00:00:00Z",
        }
    )
    app = build_app(tmp_path, miniflux_client)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/miniflux/entry/10")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["entry"]["id"] == 10


def test_debug_miniflux_entry_gateway_not_found(tmp_path):
    def raise_not_found(_entry_id):
        raise MinifluxGatewayError("not found", status_code=404, reason="missing")

    miniflux_client = SimpleNamespace(get_entry=raise_not_found)
    app = build_app(tmp_path, miniflux_client)
    client = app.test_client()
    response = client.get("/miniflux-ai/user/miniflux/entry/10")
    payload = response.get_json()
    assert response.status_code == 404
    assert payload["message"] == "entry not found"
