# Web UI API Reference

This document contains the API details used by the Debug UI (`/debug/`), including task observability and saved entries.

## Task observability APIs

- `GET /miniflux-ai/user/tasks?status=&limit=&offset=&include_payload=`
  - List durable tasks (`status` optional, `limit` defaults to `100`, max `500`, `include_payload` defaults to `false`).
- `GET /miniflux-ai/user/tasks/<task_id>`
  - Query one task by id.
- `GET /miniflux-ai/user/tasks/metrics`
  - Return queue and flow metrics (`window_seconds` optional, default `300`, range `60-3600`):
    - queue water level: `pending/running/retryable/dead/done`, `total`, `backlog`
    - runnable depth: `ready_to_claim`, `delayed_retry`
    - flow/quality: `throughput_done_per_minute`, `terminal_failure_rate`, `terminal_failure_rate_window`
    - retry pressure: `retries_total_estimated`, `retries_per_task_estimated`, `avg_attempts_done`, `avg_attempts_dead`
- `GET /miniflux-ai/user/tasks/failure-groups?status=&error=&error_key=&limit=&offset=`
  - Aggregate failed tasks by `status + normalized error_key` for quick triage (`status` optional: `retryable|dead`).
  - `error` will be normalized into `error_key` (numbers/UUID/URL noise removed) for stable grouping.
- `GET /miniflux-ai/user/tasks/failure-groups/tasks?status=&error=&error_key=&limit=&offset=&include_payload=`
  - Drill down from failure groups to concrete failed task samples.
- `POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - Requeue by failure group filter (`status` optional `retryable|dead`; `error` or `error_key` optional).
- `POST /miniflux-ai/user/tasks/<task_id>/requeue`
  - Requeue one task (supported source states: `dead|retryable|running`) to `pending`.
- `POST /miniflux-ai/user/tasks/requeue`
  - Batch requeue by filter (`status` default `dead`; optional `error`/`error_key` normalized group filter; `limit` default `100`).

## Saved entries API

- `GET /miniflux-ai/user/saved-entries?title=&match=&limit=&offset=`
  - Query persisted saved-entry records; supports optional title filter.
  - `title` optional: when omitted, returns all saved entries with pagination.
  - Optional:
    - `match`: `prefix` (default) | `contains` | `exact`
    - `limit`: default `50`, max `500`
    - `offset`: default `0`
  - Returns:
    - pagination fields (`count`, `total`, `limit`, `offset`)
    - `entries[]` with `canonical_id`, `entry_id`, `title`, `url`, `feed_title`, `save_count`, `first_saved_at`, `last_saved_at`.

## Saved entries source backfill

- To backfill historical records where `feed_title` is empty:
  - `uv run python scripts/backfill_saved_entries_feed_title.py --config config.yml --batch-size 200`

## Debug UI quick notes

- Enable `debug.enabled: true`, then open `/debug/`.
- `任务排障` panel supports a minimum operational loop:
  - Query failure groups: `GET /miniflux-ai/user/tasks/failure-groups`
  - View sample tasks: `GET /miniflux-ai/user/tasks/failure-groups/tasks`
  - Query task detail: `GET /miniflux-ai/user/tasks/<task_id>`
  - Batch requeue by filter/group: `POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - Requeue one task: `POST /miniflux-ai/user/tasks/<task_id>/requeue`
- Use this panel to quickly identify hot failures (`status + error_key`) and execute manual retries.
