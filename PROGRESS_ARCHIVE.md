# Progress Archive

Date: 2026-02-25

## Current Baseline

- Unit tests command:
  - `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`
- Latest result:
  - `Ran 36 tests in 0.089s ... OK` (2026-02-25)

## Completed Refactors

- Unified JSON file helpers and locking:
  - `common/json_storage.py`
- Introduced typed service containers:
  - `myapp/services.py` (`AppServices`)
  - `main.py` (`RuntimeServices`)
- Consolidated polling/webhook batch orchestration:
  - `core/process_entries_batch.py`
- Added adapter layer:
  - `adapters/miniflux_gateway.py`
  - `adapters/llm_gateway.py`
  - `adapters/protocols.py`
- Split pure helper logic from core use cases:
  - `core/entry_rendering.py`
  - `core/ai_news_helpers.py`
- Added repositories:
  - `common/ai_news_repository.py`
  - `common/entries_repository.py`
- Removed legacy `entries_file/lock` passthrough from batch polling/webhook path:
  - `core/process_entries_batch.py` now submits `entry_processor(miniflux_client, entry, llm_client, logger)`
  - `core/fetch_unread_entries.py` signature now only keeps needed runtime dependencies
  - `main.py` scheduler wiring updated
  - `tests/test_batch_usecase.py`, `tests/test_webhook_api.py`, `tests/test_concurrency_integrity.py` updated accordingly
- Promoted repository-first usecase signatures:
  - `core/process_entries.py`
    - `process_entry(..., entries_repository=None)` no longer accepts `entries_file/lock`
    - rate-limited processor closure now exposes only runtime args used by batch orchestrator
  - `core/generate_daily_news.py`
    - usecase now depends on repositories (or defaults), not file path/lock plumbing
  - `main.py`
    - schedule wiring passes repositories to daily-news usecase directly
  - `tests/test_data_integrity.py` and `tests/test_concurrency_integrity.py` updated to construct repositories explicitly
- Slimmed service containers to depend on repositories/gateways only:
  - `myapp/services.py` (`AppServices`) removed raw file-path/lock fields
  - `main.py` (`RuntimeServices`) removed raw file-path/lock fields
  - `myapp/__init__.py` stores only runtime collaborators used by routes
  - `tests/test_service_containers.py` assertions updated for repository-centric contract
- App factory is now repository-only at the dependency layer:
  - `myapp/__init__.py#create_app` accepts repositories (no file path/lock parameters)
  - default repositories are created internally only when caller does not inject them
  - container/API tests updated to pass repositories where persistence path matters
  - added default-path contract test for app factory fallback repositories
- README architecture section updated to document dependency flow:
  - `gateway -> usecase -> repository`
  - includes `create_app` repository-injection integration snippet
- Added release note:
  - `CHANGELOG.md` documents app-factory API simplification and migration notes

## Current Service Wiring

- Runtime bootstrap injects:
  - `EntriesRepository(path='entries.json', lock=file_lock)`
  - `AiNewsRepository(path='ai_news.json', lock=file_lock)`
- Flask app services carry both repositories and gateway clients.

## Remaining Cleanup (Next)

- No blocking refactor items identified.

## Notes

- User requested ignoring `EnhanceFeaturePlan/` directory.
- `.gitignore` appears modified in working tree but was not changed by this refactor sequence.
