import markdown


def build_summary_entry(entry, response_content):
    feed = entry.get('feed') or {}
    category = feed.get('category') or {}
    dt = entry.get('created_at') or entry.get('published_at') or entry.get('date') or ''
    return {
        'datetime': dt,
        'category': category.get('title') or '',
        'title': entry.get('title') or '',
        'content': response_content,
        'url': entry.get('url') or '',
    }


def render_agent_response(agent_config, response_content):
    text = (response_content or '').replace('\r', '')
    if agent_config['style_block']:
        compact = text.replace('\n', '')
        return (
            '<blockquote>\n  <p><strong>'
            + agent_config['title']
            + '</strong> '
            + compact
            + '\n</p>\n</blockquote><br/>'
        )

    return f"{agent_config['title']}{markdown.markdown(text)}<hr><br />"
