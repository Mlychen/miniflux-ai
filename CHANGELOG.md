# Changelog

All notable changes to this project will be documented in this file.

## 2026-03-01

### Added

- Durable task observability and ops endpoints:
  - `GET /miniflux-ai/user/tasks`
  - `GET /miniflux-ai/user/tasks/<task_id>`
  - `GET /miniflux-ai/user/tasks/metrics`
  - `GET /miniflux-ai/user/tasks/failure-groups`
  - `GET /miniflux-ai/user/tasks/failure-groups/tasks`
  - `POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - `POST /miniflux-ai/user/tasks/<task_id>/requeue`
  - `POST /miniflux-ai/user/tasks/requeue`
- SQLite task schema support for normalized `error_key` grouping.
- Minimal Debug UI task-ops panel:
  - failure group query
  - failed task sample query
  - task detail query by `task_id`
  - filter-based requeue
  - group/task requeue actions

### Changed

- Webhook main path is durable-task only; no fallback to in-memory queue or sync processing.
- Documentation refreshed for task-state architecture and debug workflow.

## 2026-02-26

### Added

- New config options for single-entry mode:
  - `miniflux.entry_mode`: `auto | webhook | polling`, default `auto`
  - `miniflux.webhook_queue_max_size`: queue max size, default 1000
  - `miniflux.webhook_queue_workers`: background workers, default 2
  - `miniflux.dedup_marker`: dedup marker, default `<!-- miniflux-ai:processed -->`
- New repository: `ProcessedEntriesRepository` for tracking processed entry IDs
- New module: `core/queue.py` with `QueueBackend` protocol and `InMemoryQueueBackend` implementation

### Changed

- Simplified entry mode: now only one entry (webhook OR polling) is active based on config
- `process_entry()` now supports deduplication via:
  - Content marker detection
  - Processed entries tracking
- `build_rate_limited_processor()` now accepts `processed_entries_repository` parameter
- **Queue integration complete**: Webhook requests now return 202 Accepted and are processed asynchronously via background workers
- `myapp/__init__.py`: Flask app now accepts optional `webhook_queue` parameter
- `myapp/webhook_ingest.py`: Webhook handler now uses queue when available, returns 202 for async processing
- `main.py`: `my_flask()` now creates and starts webhook queue consumer threads

### Migration Notes

- If using webhook mode, configure `miniflux.entry_mode` and `miniflux.webhook_secret`
- Default `entry_mode=auto` maintains backward compatibility
- Webhook mode now returns 202 (Accepted) instead of blocking until processing completes

All notable changes to this project will be documented in this file.

## 2026-02-26

### Added

- New config options for single-entry mode:
  - `miniflux.entry_mode`: `auto | webhook | polling`, default `auto`
  - `miniflux.webhook_queue_max_size`: queue max size, default 1000
  - `miniflux.webhook_queue_workers`: background workers, default 2
  - `miniflux.dedup_marker`: dedup marker, default `<!-- miniflux-ai:processed -->`
- New repository: `ProcessedEntriesRepository` for tracking processed entry IDs
- New module: `core/queue.py` with `QueueBackend` protocol and `InMemoryQueueBackend` implementation

### Changed

- Simplified entry mode: now only one entry (webhook OR polling) is active based on config
- `process_entry()` now supports deduplication via:
  - Content marker detection
  - Processed entries tracking
- `build_rate_limited_processor()` now accepts `processed_entries_repository` parameter

### Migration Notes

- If using webhook mode, configure `miniflux.entry_mode` and `miniflux.webhook_secret`
- Default `entry_mode=auto` maintains backward compatibility

## 2026-02-25

All notable changes to this project will be documented in this file.

## 2026-02-25

### Changed

- Refactored layering to repository-first dependency flow (`gateway -> usecase -> repository`).
- Simplified batch orchestration:
  - `core.process_entries_batch.process_entries_batch(...)` now invokes processors with runtime args only.
  - `core.fetch_unread_entries.fetch_unread_entries(...)` no longer passes file path/lock plumbing.
- Simplified core usecase signatures:
  - `core.process_entries.process_entry(...)` now depends on `entries_repository`.
  - `core.generate_daily_news.generate_daily_news(...)` now depends on repositories.
- Simplified service containers:
  - `myapp.services.AppServices` and `main.RuntimeServices` now store runtime collaborators, not raw file path/lock fields.
- Simplified Flask app factory:
  - `myapp.create_app(...)` now uses repository dependencies directly.
  - Removed app-factory file/lock parameters (`entries_file`, `ai_news_file`, `file_lock`).

### Tests

- Added/updated coverage for:
  - batch orchestration behavior
  - repository contracts
  - service container wiring
  - webhook and AI news API behavior
- Current full baseline:
  - `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`
  - `Ran 36 tests ... OK`

### Migration Notes

- If downstream code called `create_app(...)` with file-path arguments, migrate to repository injection:
  - construct `EntriesRepository` and `AiNewsRepository`
  - pass them as `entries_repository` and `ai_news_repository`
