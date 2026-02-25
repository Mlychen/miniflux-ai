# Dependency Injection Migration (Current Refactor)

This document maps old call patterns to the new explicit dependency-injection signatures.

## 1) Config and Logger

### Old

```python
from common import Config, logger
config = Config()
```

### New

```python
from common.config import Config
from common.logger import get_logger

config = Config.from_file("config.yml")
logger = get_logger(config.log_level)
```

For tests:

```python
config = Config.from_dict({...})
```

## 2) LLM Client Construction

### Old

`core/get_ai_result.py` created `llm_client` at import time.

### New

```python
from core.get_ai_result import build_llm_client

llm_client = build_llm_client(config)
```

## 3) AI Result Call

### Old

```python
get_ai_result(prompt, request)
```

### New

```python
get_ai_result(llm_client, config, prompt, request, logger=None)
```

## 4) Entry Processing

### Old

```python
process_entry(miniflux_client, entry)
```

### New

```python
process_entry(
    miniflux_client,
    entry,
    config,
    llm_client,
    logger,
    entries_file="entries.json",
    lock=None,
)
```

If you need rate limiting wrapper:

```python
entry_processor = build_rate_limited_processor(config)
entry_processor(miniflux_client, entry, llm_client, logger, "entries.json", lock)
```

## 5) Fetch Unread Entries

### Old

```python
fetch_unread_entries(config, miniflux_client)
```

### New

```python
fetch_unread_entries(
    config,
    miniflux_client,
    entry_processor,
    llm_client,
    logger,
    entries_file="entries.json",
    lock=None,
)
```

## 6) Daily News Generation

### Old

```python
generate_daily_news(miniflux_client)
```

### New

```python
generate_daily_news(
    miniflux_client,
    config,
    llm_client,
    logger,
    entries_file="entries.json",
    ai_news_file="ai_news.json",
)
```

## 7) Flask App Creation

### Old

Imported global `app` from `myapp`.

### New

```python
from myapp import create_app

app = create_app(
    config,
    miniflux_client,
    llm_client,
    logger,
    entry_processor,
    entries_file="entries.json",
    ai_news_file="ai_news.json",
)
```

Routes now use app-injected services from `current_app.config["APP_SERVICES"]`.

## 8) Recommended Command Runner

Use `uv` as the default command runner for local development:

```bash
uv venv .venv
uv pip install -r requirements-dev.txt
uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity
uv run python main.py
```

## 9) Test Modularization Update

The local test suite is split into explicit modules:

- `tests.test_filter` (filter logic)
- `tests.test_config` (config loading)
- `tests.test_data_integrity` (entries/ai-news lifecycle and idempotency)

Run all local modules:

```bash
uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity
```

Unified test map and prompts:

- `TESTING_GUIDE.md`
