from dataclasses import dataclass
from typing import Any

from common.json_storage import consume_json_file, write_json_file


@dataclass(frozen=True)
class AiNewsRepository:
    path: str
    lock: Any = None

    def save_latest(self, content: str):
        write_json_file(self.path, content, lock=self.lock)

    def consume_latest(self) -> str:
        return consume_json_file(
            self.path,
            empty_value='',
            default_factory=lambda: '',
            lock=self.lock,
        )
