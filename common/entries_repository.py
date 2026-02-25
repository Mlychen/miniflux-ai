from dataclasses import dataclass
from typing import Any

from common.json_storage import append_json_list_item, read_json_file, write_json_file


@dataclass(frozen=True)
class EntriesRepository:
    path: str
    lock: Any = None

    def append_summary_item(self, item):
        append_json_list_item(self.path, item, lock=self.lock)

    def read_all(self):
        return read_json_file(self.path, default_factory=list, lock=self.lock)

    def clear_all(self):
        write_json_file(self.path, [], lock=self.lock)
