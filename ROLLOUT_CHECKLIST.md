# Rollout Checklist

## 1) Pre-flight

1. Create environment:
   - `uv venv .venv`
2. Install dependencies:
   - `uv pip install -r requirements-dev.txt`
3. Verify tests:
   - `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity`
4. (Alternative without uv)
   - `pip install -r requirements-dev.txt`
   - `python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity`

## 2) Runtime Smoke Test

1. Use your real config file:
   - `uv run python -c "from main import bootstrap; s=bootstrap('config.yml'); print('bootstrap ok')"`
2. Start service:
   - `uv run python main.py`
3. Verify log lines:
   - Miniflux connected
   - schedule added
   - webhook endpoint started (if enabled)

## 3) Functional Checks

1. Polling path:
   - Ensure unread entries are fetched and updated.
2. Webhook path:
   - Send signed webhook payload and verify 200.
   - Missing/invalid signature should return 403.
3. AI news path:
   - Wait for scheduled run and verify `/rss/ai-news` returns new entry.

## 4) 24h Gray Observation

1. Track error rate in logs:
   - Exceptions in schedule loop
   - LLM timeout/errors
2. Track data integrity:
   - `entries.json` is cleared after daily news generation
   - No duplicated content prefixes in updated entries
3. Track API behavior:
   - Webhook 403 ratio only from invalid requests

## 5) Release Gate

Proceed only if all conditions pass:

1. Unit tests pass.
2. Runtime smoke test passes.
3. Polling/webhook/ai-news all pass.
4. No abnormal error spikes in 24h gray.
