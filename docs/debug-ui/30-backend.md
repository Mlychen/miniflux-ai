# 30. 后端接口现状与增强建议

本项目提供 Debug UI 依赖的接口（全部位于 `/miniflux-ai/*` 前缀下）。

## 已有接口（Debug UI MVP 依赖）

### 手动触发处理

- `POST /miniflux-ai/manual-process`
- body：`{"entry_id": 123}`
- 返回：
  - 200：`{"status":"ok","entry_id":"123"}`
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

## Debug 友好增强建议（可选）

这些增强不是 Debug UI MVP 的硬要求，但会显著提升排障效率。

### 建议 1：增加 debug 信息接口

- `GET /miniflux-ai/debug/info`
- 返回建议字段：
  - `version` / `build_time`
  - `entry_mode`（polling/webhook）
  - `http_api_enabled`
  - `storage_backend`（json/sqlite）
  - `llm_pool` 配置（隐去敏感信息）

用途：Debug UI 首页直接展示运行态信息，避免“接口 404 是没启动 Flask 还是路由问题”。

### 建议 2：为每次 manual-process 增加 trace_id

- `manual-process` 响应里返回 `trace_id`
- 日志统一带上该 trace_id

用途：Debug UI 中点击一次触发，可直接用 trace_id 在日志中定位全链路。

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
