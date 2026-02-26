from dataclasses import dataclass
from typing import Any, List

from common.json_storage import append_json_list_item, read_json_file, write_json_file


@dataclass(frozen=True)
class ProcessedEntriesRepository:
    """Repository for tracking processed entry IDs to support deduplication."""

    path: str
    lock: Any = None

    def contains(self, entry_id: str) -> bool:
        """Check if an entry ID has already been processed."""
        processed_ids = self.read_all()
        return entry_id in processed_ids

    def add(self, entry_id: str):
        """Mark an entry ID as processed."""
        # Only add if not already present
        processed_ids = self.read_all()
        if entry_id not in processed_ids:
            append_json_list_item(self.path, entry_id, lock=self.lock)

    def read_all(self) -> List[str]:
        """Read all processed entry IDs."""
        return read_json_file(self.path, default_factory=list, lock=self.lock)

    def clear_all(self):
        """Clear all processed entry IDs."""
        write_json_file(self.path, [], lock=self.lock)
