import argparse
from typing import Dict, List, Optional

from app.infrastructure.config import Config
from app.infrastructure.miniflux_gateway import MinifluxGateway
from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill empty feed_title for saved_entries records."
    )
    parser.add_argument(
        "--config",
        default="config.yml",
        help="Path to config file (default: config.yml)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of rows per batch (default: 200)",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Maximum number of batches to process (0 means unlimited)",
    )
    return parser.parse_args()


def _parse_int(value) -> Optional[int]:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return None


def _load_feed_map(miniflux_client: MinifluxGateway) -> Dict[int, str]:
    feed_map: Dict[int, str] = {}
    feeds = miniflux_client.get_feeds() or []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        feed_id = _parse_int(feed.get("id"))
        if feed_id is None:
            continue
        title = str(feed.get("title") or "").strip()
        if not title:
            category = feed.get("category")
            if isinstance(category, dict):
                title = str(category.get("title") or "").strip()
        if title:
            feed_map[feed_id] = title
    return feed_map


def _resolve_source_title(miniflux_client: MinifluxGateway, feed_map: Dict[int, str], entry_id) -> str:
    eid = _parse_int(entry_id)
    if eid is None:
        return ""
    entry = miniflux_client.get_entry(eid) or {}
    if not isinstance(entry, dict):
        return ""
    feed_id = _parse_int(entry.get("feed_id"))
    if feed_id is None:
        feed = entry.get("feed")
        if isinstance(feed, dict):
            feed_id = _parse_int(feed.get("id"))
    if feed_id is None:
        return ""
    return str(feed_map.get(feed_id) or "").strip()


def run_backfill(config_path: str, batch_size: int, max_batches: int) -> Dict[str, int]:
    config = Config.from_file(config_path)
    sqlite_path = getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")
    repository = SavedEntriesRepositorySQLite(path=sqlite_path)
    miniflux_client = MinifluxGateway(config.miniflux_base_url, config.miniflux_api_key)
    feed_map = _load_feed_map(miniflux_client)

    stats = {"scanned": 0, "updated": 0, "skipped": 0, "failed": 0, "batches": 0}
    batch_size = max(1, int(batch_size))

    while True:
        if max_batches > 0 and stats["batches"] >= max_batches:
            break

        rows: List[Dict[str, object]] = repository.list_missing_feed_title(limit=batch_size)
        if not rows:
            break

        stats["batches"] += 1
        for row in rows:
            stats["scanned"] += 1
            row_id = row.get("id")
            entry_id = row.get("entry_id")
            canonical_id = str(row.get("canonical_id") or "").strip()
            if entry_id is None and canonical_id.isdigit():
                entry_id = int(canonical_id)
            if entry_id is None:
                stats["skipped"] += 1
                continue
            try:
                title = _resolve_source_title(miniflux_client, feed_map, entry_id)
                if not title:
                    stats["skipped"] += 1
                    continue
                ok = repository.update_feed_title(int(row_id), title)
                if ok:
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                stats["failed"] += 1

    return stats


def main():
    args = parse_args()
    stats = run_backfill(
        config_path=args.config,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
    )
    print(
        "backfill saved_entries feed_title completed: "
        f"batches={stats['batches']} scanned={stats['scanned']} "
        f"updated={stats['updated']} skipped={stats['skipped']} failed={stats['failed']}"
    )


if __name__ == "__main__":
    main()
