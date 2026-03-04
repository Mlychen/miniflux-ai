# Web UI 接口参考

本文汇总 Debug UI（`/debug/`）使用的接口，包括任务可观测性与保存条目查询。

## 任务可观测性 API

- `GET /miniflux-ai/user/tasks?status=&limit=&offset=&include_payload=`
  - 列出持久化任务（`status` 可选，`limit` 默认 `100`，最大 `500`，`include_payload` 默认 `false`）。
- `GET /miniflux-ai/user/tasks/<task_id>`
  - 通过 ID 查询单个任务。
- `GET /miniflux-ai/user/tasks/metrics`
  - 返回队列和流量指标（`window_seconds` 可选，默认 `300`，范围 `60-3600`）：
    - 队列水位：`pending/running/retryable/dead/done`, `total`, `backlog`
    - 可运行深度：`ready_to_claim`, `delayed_retry`
    - 流量/质量：`throughput_done_per_minute`, `terminal_failure_rate`, `terminal_failure_rate_window`
    - 重试压力：`retries_total_estimated`, `retries_per_task_estimated`, `avg_attempts_done`, `avg_attempts_dead`
- `GET /miniflux-ai/user/tasks/failure-groups?status=&error=&error_key=&limit=&offset=`
  - 按 `status + normalized error_key` 聚合失败任务以便快速分类（`status` 可选：`retryable|dead`）。
  - `error` 会归一化为 `error_key`（去除数字/UUID/URL 噪声）以便稳定分组。
- `GET /miniflux-ai/user/tasks/failure-groups/tasks?status=&error=&error_key=&limit=&offset=&include_payload=`
  - 从失败分组下钻到具体失败任务样本。
- `POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - 按失败分组过滤器重新入队（`status` 可选 `retryable|dead`；`error` 或 `error_key` 可选）。
- `POST /miniflux-ai/user/tasks/<task_id>/requeue`
  - 重新入队单个任务（支持源状态：`dead|retryable|running`）到 `pending`。
- `POST /miniflux-ai/user/tasks/requeue`
  - 按过滤器批量重新入队（`status` 默认 `dead`；可选 `error`/`error_key` 归一化分组过滤器；`limit` 默认 `100`）。

## 已保存条目查询 API

- `GET /miniflux-ai/user/saved-entries?title=&match=&limit=&offset=`
  - 查询 `save_entry` 管线持久化结果，支持按标题过滤。
  - `title` 可选：不传时按分页返回全部保存条目。
  - 可选：
    - `match`: `prefix`（默认）| `contains` | `exact`
    - `limit`: 默认 `50`，最大 `500`
    - `offset`: 默认 `0`
  - 返回：
    - 分页字段（`count`, `total`, `limit`, `offset`）
    - `entries[]`（包含 `canonical_id`, `entry_id`, `title`, `url`, `feed_title`, `save_count`, `first_saved_at`, `last_saved_at`）。

## 保存条目来源回填

- 若历史数据 `feed_title` 为空，可执行：
  - `uv run python scripts/backfill_saved_entries_feed_title.py --config config.yml --batch-size 200`

## Debug UI 使用说明（简版）

- 启用 `debug_enabled: true`，然后打开 `/debug/`。
- `任务排障` 面板支持最小闭环：
  - 查询失败分组：`GET /miniflux-ai/user/tasks/failure-groups`
  - 查看分组任务样本：`GET /miniflux-ai/user/tasks/failure-groups/tasks`
  - 查询任务详情：`GET /miniflux-ai/user/tasks/<task_id>`
  - 按筛选/分组重入队：`POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - 单任务重入队：`POST /miniflux-ai/user/tasks/<task_id>/requeue`
- 该面板用于快速定位失败热点（`status + error_key`）并执行人工重试。
