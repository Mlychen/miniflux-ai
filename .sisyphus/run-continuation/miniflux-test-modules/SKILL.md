---
name: miniflux-test-modules
description: Modular test orchestration for the miniflux-ai project. Use when running, reporting, or debugging tests by module (filter/config/data-integrity) or when executing live integration checks (Miniflux, webhook, AI News) with uv.
---

# Miniflux Test Modules Skill

Run tests in modules and keep reports consistent.

## Execute module tests

Use the script:

```powershell
scripts/run-module-tests.ps1 -Module <filter|config|integrity|unit-all>
```

Or run commands directly:

- `uv run python -m unittest -q tests.test_filter`
- `uv run python -m unittest -q tests.test_config`
- `uv run python -m unittest -q tests.test_data_integrity`
- `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity`

## Execute live integration checks

For live checks, read:

- `references/live-checklist.md`

For model prompts and expected reporting format, read:

- `references/prompt-templates.md`

## Report format

Always report:

1. Command(s) executed
2. Pass/fail by module
3. Blocking issue (if any)
4. Next actionable step

