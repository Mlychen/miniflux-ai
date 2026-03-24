import fnmatch


def build_processed_prefixes(config):
    prefixes = []
    for _, agent_cfg in config.agents.items():
        title = agent_cfg["title"]
        prefixes.append(title)
        if agent_cfg.get("style_block"):
            prefixes.append(f"<blockquote>\n  <p><strong>{title}</strong>")
    return tuple(prefixes)


def is_entry_already_rendered(config, entry):
    content = entry.get("content") or ""
    prefixes = build_processed_prefixes(config)
    return bool(prefixes) and content.startswith(prefixes)


def filter_entry(config, agent, entry):
    # Todo Compatible with whitelist/blacklist parameter, to be removed
    allow_list = agent[1].get('allow_list') if agent[1].get('allow_list') is not None else agent[1].get('whitelist')
    deny_list = agent[1]['deny_list'] if agent[1].get('deny_list') is not None else agent[1].get('blacklist')
    if isinstance(allow_list, list) and len(allow_list) == 0:
        allow_list = None
    if isinstance(deny_list, list) and len(deny_list) == 0:
        deny_list = None

    # filter, if not content starts with start flag
    if not is_entry_already_rendered(config, entry):

        # filter, if in allow_list
        if allow_list is not None:
            if any(fnmatch.fnmatch(entry['feed']['site_url'], pattern) for pattern in allow_list):
                return True

        # filter, if not in deny_list
        elif deny_list is not None:
            if any(fnmatch.fnmatch(entry['feed']['site_url'], pattern) for pattern in deny_list):
                return False
            else:
                return True

        # filter, if allow_list and deny_list are both None
        elif allow_list is None and deny_list is None:
            return True

    return False
