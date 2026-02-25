import markdown


def build_summary_entry(entry, response_content):
    return {
        'datetime': entry['created_at'],
        'category': entry['feed']['category']['title'],
        'title': entry['title'],
        'content': response_content,
        'url': entry['url'],
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
