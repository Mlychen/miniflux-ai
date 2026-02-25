# Prompt Templates

## Run one module

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

## Run full unit baseline

```text
Run:
uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity

Return:
1) summary counts
2) failures with file::test
3) release risk level (low/medium/high)
```

## Run live integration smoke

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

