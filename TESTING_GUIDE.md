# Testing Guide

This is the single entry point for test execution, live verification, and LLM test prompts.

## 1) Local Unit Modules

### filter

- Scope: feed filtering and duplicate-guard behavior.
- Command:
  - `uv run python -m unittest -q tests.test_filter`

### config

- Scope: config parsing from dict/file and key mapping.
- Command:
  - `uv run python -m unittest -q tests.test_config`

### integrity

- Scope:
  - `entries.json` persistence correctness
  - idempotent skip for processed entries
  - AI news generation and cleanup consistency
- Command:
  - `uv run python -m unittest -q tests.test_data_integrity`

### unit-all

- Scope: all local unit modules.
- Command:
  - `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity`

## 2) Live Integration Flow

1. Bootstrap:
   - `uv run python -c "from main import bootstrap; s=bootstrap('config.yml'); print('bootstrap ok')"`
2. Miniflux connectivity:
   - `uv run python -c "import miniflux; from common.config import Config; c=Config.from_file('config.yml'); cli=miniflux.Client(c.miniflux_base_url, api_key=c.miniflux_api_key); print(cli.me().get('username'))"`
3. Webhook checks:
   - invalid signature -> expect `403`
   - valid signature -> expect `200`
4. Polling check:
   - one `fetch_unread_entries(...)` run
5. AI News check:
   - one `generate_daily_news(...)` run
   - `GET /rss/ai-news` returns content

For release gating and 24h observation criteria, use:

- `ROLLOUT_CHECKLIST.md`

## 3) LLM Prompt Templates

### Prompt A: Run one module

```text
Run miniflux-ai test module: {filter|config|integrity}.
Use uv commands.
Do not modify code.
Return:
1) command used
2) pass/fail
3) failed test names
4) shortest fix action
```

### Prompt B: Run full unit baseline

```text
Run:
uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity

Return:
1) summary counts
2) failures with file::test
3) release risk level (low/medium/high)
```

### Prompt C: Run live smoke

```text
Validate miniflux-ai live path with current config.yml:
1) bootstrap check
2) Miniflux me() check
3) webhook invalid signature -> expect 403
4) webhook valid signature -> expect 200
5) one polling run
6) daily news generation + rss check

Return final gate: GO or NO-GO.
```

### Prompt D: Integrity focus

```text
Run integrity-focused validation for miniflux-ai.
Required:
- tests.test_data_integrity
- one live generate_daily_news run (if config is available)

Evaluate:
1) entries.json lifecycle
2) ai_news.json lifecycle
3) duplicate-processing risk
4) concurrency/file-lock risk

Return:
- findings ordered by severity
- concrete remediation list
```

## 4) Skill Shortcut

Run module tests through skill script:

- `powershell -NoProfile -ExecutionPolicy Bypass -File .sisyphus/run-continuation/miniflux-test-modules/scripts/run-module-tests.ps1 -Module unit-all`
