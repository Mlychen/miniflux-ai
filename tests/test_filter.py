import unittest

from common.config import Config
from core.entry_filter import filter_entry


def make_config(agent_cfg):
    return Config.from_dict({"agents": {"test": agent_cfg}})

def make_entry(content="raw content", site_url="https://example.com/post"):
    return {
        "content": content,
        "feed": {"site_url": site_url},
    }


class TestEntryFilter(unittest.TestCase):
    def test_block_when_already_prefixed_by_title(self):
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
        self.assertFalse(filter_entry(config, agent, entry))

    def test_allow_list_match(self):
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
        self.assertTrue(filter_entry(config, agent, entry))

    def test_deny_list_match(self):
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
        self.assertFalse(filter_entry(config, agent, entry))

    def test_deny_list_not_match(self):
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
        self.assertTrue(filter_entry(config, agent, entry))


if __name__ == "__main__":
    unittest.main()
