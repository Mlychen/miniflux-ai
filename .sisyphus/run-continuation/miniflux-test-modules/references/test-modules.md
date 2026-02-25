# Test Modules

## filter

- File: `tests/test_filter.py`
- Command: `uv run python -m unittest -q tests.test_filter`
- Purpose: Validate filtering rules and duplicate-guard behavior.

## config

- File: `tests/test_config.py`
- Command: `uv run python -m unittest -q tests.test_config`
- Purpose: Validate config parsing and field mapping.

## integrity

- File: `tests/test_data_integrity.py`
- Command: `uv run python -m unittest -q tests.test_data_integrity`
- Purpose: Validate JSON lifecycle and idempotency behavior.

## unit-all

- Command: `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity`
- Purpose: Full local unit baseline.

