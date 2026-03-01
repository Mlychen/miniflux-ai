# 30. 后端接口现状与增强建议

本项目提供 Debug UI 依赖的接口（全部位于 `/miniflux-ai/*` 前缀下）。

## 已有接口（Debug UI MVP 依赖）

### 手动触发处理

- `POST /miniflux-ai/manual-process`
- body：
  - `{"entry_id": 123}`
  - 或 `{"entry_id": 123, "trace_id": "32位hex字符串"}`
- 返回：
  - 200：`{"status":"ok","entry_id":"123","trace_id":"..."}`
  - 400：缺少/非法 entry_id
  - 404：entry 不存在
  - 500：处理失败

实现位置：`myapp/__init__.py` 内的 `manual_process`。

### 请求池指标

- `GET /miniflux-ai/user/llm-pool/metrics`
- 返回：`{"status":"ok","metrics":{"total_calls":...,"total_errors":...,"total_rejected":...}}`

### 失败条目列表

- `GET /miniflux-ai/user/llm-pool/failed-entries?limit=100`
- 返回：`{"status":"ok","items":[...]}`

items 每项通常包含：
- `entry_key`
- `status`
- `attempts_used`
- `max_attempts`
- `created_at`
- `last_attempt_at`
- `ttl_seconds`
- `url`（可能为空）

### 清空/重置请求池

- `POST /miniflux-ai/user/llm-pool/clear`
- body：
  - `{}`
  - 或 `{"entry_key":"..."}`

## 任务排障接口（已实现）

### 任务详情

- `GET /miniflux-ai/user/tasks/<task_id>`
- 返回：
  - 200：`{"status":"ok","task":{...}}`
  - 404：`{"status":"not_found","task_id":"..."}`
  - 400：`{"status":"error","message":"invalid task_id"}`

### 失败分组列表

- `GET /miniflux-ai/user/tasks/failure-groups?status=&error=&error_key=&limit=&offset=`
- 返回：
  - `status_filter`：可选 `retryable|dead`
  - `error_key_filter`：对 `error` 归一化后的分组键
  - `groups[]`：`status/error_key/error/count/latest_updated_at/oldest_created_at`

### 失败分组任务样本

- `GET /miniflux-ai/user/tasks/failure-groups/tasks?status=&error=&error_key=&limit=&offset=&include_payload=`
- 返回：
  - `tasks[]`：任务详情（默认不含 payload，可通过 `include_payload=true` 打开）

### 按分组批量重入队

- `POST /miniflux-ai/user/tasks/failure-groups/requeue`
- body：
  - `status`：可选 `retryable|dead`
  - `error` 或 `error_key`：可选
  - `limit`：最多重入队数量
- 返回：`{"status":"ok","requeued":N,...}`

### 单任务重入队

- `POST /miniflux-ai/user/tasks/<task_id>/requeue`
- 返回：
  - 200：`{"status":"ok","task_id":"...","requeued":true}`
  - 404：`{"status":"not_found","task_id":"..."}`

## Debug 友好增强建议（可选）

这些增强不是 Debug UI MVP 的硬要求，但会显著提升排障效率。

### 建议 1：增加 debug 信息接口

- `GET /miniflux-ai/debug/info`
- 返回建议字段：
  - `version` / `build_time`
  - `entry_mode`（polling/webhook）
  - `http_api_enabled`
  - `storage_engine`（sqlite）
  - `llm_pool` 配置（隐去敏感信息）

用途：Debug UI 首页直接展示运行态信息，避免“接口 404 是没启动 Flask 还是路由问题”。

### 已实现：manual-process trace_id 透传

- `manual-process` 支持可选请求字段 `trace_id`
- 若未传入，后端会自动生成 `trace_id`
- 响应始终返回 `trace_id`
- 处理追踪日志统一带该 `trace_id`

用途：Debug UI 点击一次触发后，可直接按 `trace_id` 查询完整处理链路。

### 建议 3：最近处理记录（轻量审计）

- `GET /miniflux-ai/debug/recent?limit=50`
- 返回最近 N 次手动触发的时间、entry_id、结果、耗时、错误摘要

用途：Debug UI 不需要翻日志即可看到近期行为。

## 日志建议（面向调试）

- 记录：
  - 请求 URL、方法、耗时
  - entry_id / entry_key
  - LLM 调用失败原因（不要打印密钥）
- 对 manual-process：
  - 记录开始与结束（成功/失败），便于快速 grep
