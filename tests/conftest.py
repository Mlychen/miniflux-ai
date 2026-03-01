from types import SimpleNamespace

import pytest

from common.config import Config

@pytest.fixture
def base_config():
    return Config.from_dict(
        {
            "miniflux": {
                "webhook_secret": "secret",
                "task_poll_interval": 0.1,
                "task_retry_delay_seconds": 1,
                "task_max_attempts": 3,
            },
            "agents": {
                "test": {
                    "title": "AI summary:",
                    "style_block": False,
                    "allow_list": None,
                    "deny_list": None,
                }
            },
        }
    )


@pytest.fixture
def dummy_logger():
    class DummyLogger:
        def __init__(self):
            self.messages = []

        def info(self, message):
            self.messages.append(("info", message))

        def debug(self, message):
            self.messages.append(("debug", message))

        def warning(self, message):
            self.messages.append(("warning", message))

        def error(self, message):
            self.messages.append(("error", message))

    return DummyLogger()


@pytest.fixture
def dummy_clients():
    return SimpleNamespace(), SimpleNamespace()
