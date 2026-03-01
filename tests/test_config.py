import unittest
from pathlib import Path

from common.config import Config


class TestConfig(unittest.TestCase):
    def test_from_dict(self):
        cfg = Config.from_dict(
            {
                "log_level": "DEBUG",
                "miniflux": {"base_url": "http://localhost", "api_key": "k"},
                "preprocess_prompt": "custom preprocess prompt",
            }
        )
        self.assertEqual(cfg.log_level, "DEBUG")
        self.assertEqual(cfg.miniflux_base_url, "http://localhost")
        self.assertEqual(cfg.miniflux_api_key, "k")
        self.assertEqual(cfg.preprocess_prompt, "custom preprocess prompt")

    def test_from_file(self):
        fixture = Path(__file__).resolve().parent / "fixtures_config.yml"
        cfg = Config.from_file(str(fixture))
        self.assertEqual(cfg.log_level, "INFO")
        self.assertEqual(cfg.miniflux_base_url, "http://localhost")


if __name__ == "__main__":
    unittest.main()
