from common.config import Config
from core.entry_filter import filter_entry


def make_config(agent_cfg):
    return Config.from_dict({"agents": {"test": agent_cfg}})


def make_entry(content="raw content", site_url="https://example.com/post"):
    return {
        "content": content,
        "feed": {"site_url": site_url},
    }


def test_block_when_already_prefixed_by_title():
    config = make_config(
        {
            "title": "AI summary:",
            "style_block": False,
            "allow_list": None,
            "deny_list": None,
        }
    )
    agent = next(iter(config.agents.items()))
    entry = make_entry(content="AI summary: existing")
    assert filter_entry(config, agent, entry) is False


def test_allow_list_match():
    config = make_config(
        {
            "title": "AI summary:",
            "style_block": False,
            "allow_list": ["https://home.kpmg/*"],
            "deny_list": None,
        }
    )
    agent = next(iter(config.agents.items()))
    entry = make_entry(site_url="https://home.kpmg/cn/zh/home/insights.html")
    assert filter_entry(config, agent, entry) is True


def test_empty_allow_list_treated_as_none():
    config = make_config(
        {
            "title": "AI summary:",
            "style_block": False,
            "allow_list": [],
            "deny_list": None,
        }
    )
    agent = next(iter(config.agents.items()))
    entry = make_entry(site_url="https://example.com/post")
    assert filter_entry(config, agent, entry) is True


def test_deny_list_match():
    config = make_config(
        {
            "title": "AI summary:",
            "style_block": False,
            "allow_list": None,
            "deny_list": ["https://9to5mac.com/*"],
        }
    )
    agent = next(iter(config.agents.items()))
    entry = make_entry(site_url="https://9to5mac.com/2026/02/25/post")
    assert filter_entry(config, agent, entry) is False


def test_deny_list_not_match():
    config = make_config(
        {
            "title": "AI summary:",
            "style_block": False,
            "allow_list": None,
            "deny_list": ["https://9to5mac.com/*"],
        }
    )
    agent = next(iter(config.agents.items()))
    entry = make_entry(site_url="https://weibo.com/1906286443/post")
    assert filter_entry(config, agent, entry) is True
