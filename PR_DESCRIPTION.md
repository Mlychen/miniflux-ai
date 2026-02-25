# PR: Repository-First Refactor (Adapters + Usecases + Repositories)

## Summary

This PR refactors the project toward a clearer dependency flow:

- `gateway -> usecase -> repository`

Core goals completed:

- Replace file-path/lock parameter plumbing with repository injection.
- Introduce adapter abstractions for Miniflux and LLM clients.
- Consolidate polling/webhook batch behavior into a shared usecase.
- Add focused tests for adapters, repositories, API routes, and service wiring.

## Key Changes

### 1) Architecture and Runtime Wiring

- Added adapters:
  - `adapters/miniflux_gateway.py`
  - `adapters/llm_gateway.py`
  - `adapters/protocols.py`
- Added typed runtime containers:
  - `myapp/services.py` (`AppServices`)
  - `main.py` (`RuntimeServices`)
- `main.py` now wires dependencies by repository/gateway objects.

### 2) Repository Layer

- Added JSON helpers:
  - `common/json_storage.py`
- Added repositories:
  - `common/entries_repository.py`
  - `common/ai_news_repository.py`

### 3) Usecase Layer

- Added shared batch orchestration:
  - `core/process_entries_batch.py`
- Updated polling/webhook paths to use shared batch flow.
- Updated usecases to repository-first signatures:
  - `core/process_entries.py`
  - `core/generate_daily_news.py`
- Extracted pure helper logic:
  - `core/entry_rendering.py`
  - `core/ai_news_helpers.py`

### 4) App Factory API Simplification

- `myapp.create_app(...)` now uses repository dependencies directly.
- Removed app-factory file/lock parameters (`entries_file`, `ai_news_file`, `file_lock`).
- Default repositories are still created internally when not injected.

## Testing

Executed full baseline:

```bash
uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository
```

Result:

- `Ran 36 tests ... OK`

## Migration Notes

If downstream code previously called:

- `create_app(..., entries_file=..., ai_news_file=..., file_lock=...)`

Migrate to:

- construct `EntriesRepository` and `AiNewsRepository`
- pass them as `entries_repository` and `ai_news_repository`

Reference:

- `CHANGELOG.md`
- `README.md` (Architecture + App Factory Integration sections)
