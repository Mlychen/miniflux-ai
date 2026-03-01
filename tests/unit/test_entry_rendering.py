from core.entry_rendering import render_agent_response


def test_render_blockquote_style():
    agent_config = {"title": "AI summary:", "style_block": True}
    output = render_agent_response(agent_config, "hello\nworld")
    assert "<blockquote>" in output
    assert "AI summary:" in output
    assert "helloworld" in output


def test_render_markdown_style():
    agent_config = {"title": "AI summary:", "style_block": False}
    output = render_agent_response(agent_config, "hello\n\nworld")
    assert output.startswith("AI summary:")
    assert "<p>" in output
    assert "hello" in output
    assert "world" in output
