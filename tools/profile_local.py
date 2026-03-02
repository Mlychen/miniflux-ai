import argparse
import cProfile
import os
import sys
import time
import tracemalloc

from markdownify import markdownify as md

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


class FakeMinifluxClient:
    def __init__(self):
        self.updated_entries = {}

    def get_entries(self, **kwargs):
        return {"total": 0, "entries": []}

    def update_entry(self, entry_id, content):
        self.updated_entries[entry_id] = content

    def get_feeds(self):
        return [{"id": 1, "title": "AI News for you"}]

    def refresh_feed(self, feed_id):
        return None


class FakeLLMClient:
    def __init__(self, simulate_markdown=True, delay_ms=0):
        self.simulate_markdown = simulate_markdown
        self.delay_ms = delay_ms

    def get_result(self, prompt, request, logger=None):
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        text = request or ""
        if self.simulate_markdown:
            try:
                text = md(text)
            except Exception:
                pass
        if len(text) > 2000:
            text = text[:2000]
        return f"{prompt[:40]}...\n{text}"


def _resolve_storage(config):
    return getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")


def _build_repositories(config):
    from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
    from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite

    sqlite_path = _resolve_storage(config)
    entries_repo = EntriesRepositorySQLite(path=sqlite_path)
    ai_news_repo = AiNewsRepositorySQLite(path=sqlite_path)
    return sqlite_path, entries_repo, ai_news_repo


def _summarize_storage_size(storage_path: str):
    if os.path.exists(storage_path):
        return os.path.getsize(storage_path)
    return 0


def run_batch_scenario(config_path: str, entries: int, content_bytes: int, max_workers: int):
    from app.infrastructure.config import Config
    from app.observability.trace import get_logger
    from app.domain.processor import (
        InMemoryProcessedNewsIds,
        build_rate_limited_processor,
    )
    from app.application.ingest_service import process_entries_batch

    config = Config.from_file(config_path)
    logger = get_logger(config.log_level)
    storage_path, entries_repo, ai_news_repo = _build_repositories(config)
    if hasattr(config, "llm_RPM"):
        config.llm_RPM = max(config.llm_RPM, entries * 2)
    if hasattr(config, "llm_max_workers"):
        config.llm_max_workers = max_workers
    processed_news_ids = InMemoryProcessedNewsIds()
    entry_processor = build_rate_limited_processor(
        config,
        entries_repository=entries_repo,
        processed_entries_repository=entries_repo,
        processed_news_ids=processed_news_ids,
    )
    fake_miniflux = FakeMinifluxClient()
    fake_llm = FakeLLMClient()
    batch_entries = []
    now = time.time()
    for i in range(entries):
        dt = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 60)
        )
        batch_entries.append(
            {
                "id": i,
                "title": f"Title {i}",
                "url": f"https://example.com/{i}",
                "content": "x" * content_bytes,
                "datetime": dt,
                "created_at": dt,
                "category": "batch",
                "feed": {
                    "site_url": "https://example.com",
                    "category": {"title": "Tech"},
                },
            }
        )
    start = time.time()
    result = process_entries_batch(
        config,
        batch_entries,
        fake_miniflux,
        entry_processor,
        fake_llm,
        logger,
    )
    elapsed_ms = (time.time() - start) * 1000.0
    storage_bytes = _summarize_storage_size(storage_path)
    print("scenario=batch")
    print(f"backend=sqlite entries={entries} content_bytes={content_bytes}")
    print(f"result={result}")
    print(f"elapsed_ms={elapsed_ms:.2f}")
    print(f"storage_bytes={storage_bytes}")


def run_ai_news_scenario(config_path: str, entries: int, content_bytes: int, simulate_llm_delay: int = 0):
    from app.infrastructure.config import Config
    from app.observability.trace import get_logger
    from app.application.news_service import generate_daily_news

    config = Config.from_file(config_path)
    logger = get_logger(config.log_level)
    storage_path, entries_repo, ai_news_repo = _build_repositories(config)
    entries_repo.clear_all()
    base = time.time()
    batch_items = []
    for i in range(entries):
        dt = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(base - i * 60)
        )
        item = {
            "id": i,
            "datetime": dt,
            "category": "科技" if i % 3 == 0 else "其他",
            "title": f"Title {i}",
            "content": "x" * content_bytes,
            "url": f"https://example.com/{i}",
        }
        batch_items.append(item)
    entries_repo.append_summary_items(batch_items)
    fake_miniflux = FakeMinifluxClient()
    fake_llm = FakeLLMClient(simulate_markdown=False, delay_ms=simulate_llm_delay)
    start = time.time()
    generate_daily_news(
        fake_miniflux,
        config,
        fake_llm,
        logger,
        ai_news_repository=ai_news_repo,
        entries_repository=entries_repo,
    )
    elapsed_ms = (time.time() - start) * 1000.0
    storage_bytes = _summarize_storage_size(storage_path)
    print("scenario=ai-news")
    print(f"backend=sqlite entries={entries} content_bytes={content_bytes}")
    print(f"elapsed_ms={elapsed_ms:.2f}")
    print(f"storage_bytes={storage_bytes}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=["batch", "ai-news"],
        required=True,
    )
    parser.add_argument("--config", default="config.yml")
    parser.add_argument("--entries", type=int, default=500)
    parser.add_argument("--content-bytes", type=int, default=4000)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--profile-out", default=None)
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--tracemalloc", action="store_true")
    parser.add_argument("--tracemalloc-top", type=int, default=30)
    parser.add_argument("--llm-delay", type=int, default=0, help="Simulated LLM delay in ms")
    args = parser.parse_args()

    def _run_scenario():
        if args.scenario == "batch":
            run_batch_scenario(
                args.config, args.entries, args.content_bytes, args.max_workers
            )
        else:
            run_ai_news_scenario(
                args.config,
                args.entries,
                max(args.content_bytes, 800),
                simulate_llm_delay=args.llm_delay
            )

    if args.tracemalloc:
        tracemalloc.start()
    profiler = cProfile.Profile()
    start_total = time.time()
    profiler.enable()
    _run_scenario()
    profiler.disable()
    total_elapsed_ms = (time.time() - start_total) * 1000.0
    print(f"total_elapsed_ms={total_elapsed_ms:.2f}")
    if args.profile_out:
        profiler.dump_stats(args.profile_out)
        print(f"pstats_saved={args.profile_out}")
    import pstats

    stats = pstats.Stats(profiler)
    stats.strip_dirs().sort_stats("cumtime").print_stats(args.top)
    if args.tracemalloc:
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")[: args.tracemalloc_top]
        print("[tracemalloc top]")
        for stat in top_stats:
            print(stat)
        tracemalloc.stop()


if __name__ == "__main__":
    main()
