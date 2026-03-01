from core.ai_news_helpers import (
    compose_daily_news_content,
    find_ai_news_feed_id,
    has_ai_news_feed,
    is_ai_news_feed_title,
)
from core.entry_rendering import build_summary_entry, render_agent_response


def test_build_summary_entry():
    entry = {
        "created_at": "2026-02-25T00:00:00Z",
        "title": "title",
        "url": "https://example.com/x",
        "feed": {"category": {"title": "News"}},
    }
    item = build_summary_entry(entry, "summary")
    assert item == {
        "datetime": "2026-02-25T00:00:00Z",
        "category": "News",
        "title": "title",
        "content": "summary",
        "url": "https://example.com/x",
    }


def test_build_summary_entry_webhook_fallback_fields():
    entry = {
        "published_at": "2026-02-25T01:02:03Z",
        "title": "title",
        "url": "https://example.com/y",
        "feed": {},
    }
    item = build_summary_entry(entry, "summary")
    assert item["datetime"] == "2026-02-25T01:02:03Z"
    assert item["category"] == ""
    assert item["title"] == "title"
    assert item["content"] == "summary"
    assert item["url"] == "https://example.com/y"


def test_render_agent_response_style_block():
    out = render_agent_response(
        {"title": "AI Summary: ", "style_block": True},
        "line1\nline2",
    )
    assert "<blockquote>" in out
    assert "AI Summary:" in out
    assert "line1line2" in out


def test_render_agent_response_markdown():
    out = render_agent_response(
        {"title": "AI Translate: ", "style_block": False},
        "**bold**",
    )
    assert out.startswith("AI Translate: ")
    assert "<strong>bold</strong>" in out
    assert out.endswith("<hr><br />")


def test_title_matching_and_feed_discovery():
    feeds = [
        {"id": 1, "title": "Other feed"},
        {"id": 77, "title": "Morning News for you"},
    ]
    assert is_ai_news_feed_title("Morning News for you")
    assert is_ai_news_feed_title("Morning News") is False
    assert has_ai_news_feed(feeds)
    assert find_ai_news_feed_id(feeds) == 77


def test_compose_daily_news_content():
    out = compose_daily_news_content("hello", "sum", "block")
    assert "hello" in out
    assert "### Summary" in out
    assert "### News" in out
    assert "sum" in out
    assert "block" in out
