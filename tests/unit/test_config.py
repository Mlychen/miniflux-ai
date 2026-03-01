from pathlib import Path

from common.config import Config


def test_from_dict():
    cfg = Config.from_dict(
        {
            "log_level": "DEBUG",
            "miniflux": {"base_url": "http://localhost", "api_key": "k"},
            "preprocess_prompt": "custom preprocess prompt",
        }
    )
    assert cfg.log_level == "DEBUG"
    assert cfg.miniflux_base_url == "http://localhost"
    assert cfg.miniflux_api_key == "k"
    assert cfg.preprocess_prompt == "custom preprocess prompt"


def test_from_file():
    fixture = Path(__file__).resolve().parent / "fixtures_config.yml"
    cfg = Config.from_file(str(fixture))
    assert cfg.log_level == "INFO"
    assert cfg.miniflux_base_url == "http://localhost"
