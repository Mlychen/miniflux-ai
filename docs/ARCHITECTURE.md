# 架构设计

本文档定义项目的核心架构设计。

## 1. 目标

- 可读性：让每个模块只做一件事，故障定位路径短。
- 可扩展：后续替换队列、存储、LLM 供应商时，不改业务主流程。
- 性能：支持突发 webhook、批处理、并发处理、可控背压。
- 健壮性：任务不因进程重启/崩溃而丢失，失败可重试、可观测。

## 2. 核心原则

1. 单一真相源：任务状态以持久化存储为准，不以进程内内存为准。
2. 单一职责：`ingest`、`worker`、`processor`、`infrastructure` 职责清晰分离。
3. 明确语义：系统采用“至少一次处理（at-least-once）+ 幂等”。
4. 原子性优先：去重/认领任务使用数据库或队列原子语义，不做 `seen()+mark()` 两步判断。

## 3. 目标模块划分

### 3.1 Ingest（入口层）

职责：
- webhook 验签与 payload 校验
- payload 规范化
- 生成 `canonical_id`
- 持久化任务（upsert）
- 返回 HTTP 状态码（`202` 仅表示“已持久化接收”）

不负责：
- 业务处理
- 重试决策
- Agent 调度

### 3.2 Worker（调度层）

职责：
- 批量 claim 任务
- 调用 processor 执行
- 根据结果写任务状态（`done`/`retryable`/`dead`）
- 执行退避重试策略

不负责：
- HTTP
- LLM/Miniflux 细节

### 3.3 Processor（领域处理层）

职责：
- preprocess
- agent 执行
- 结果渲染
- 更新 Miniflux
- 写摘要结果

不负责：
- 队列状态管理
- 任务重试管理

### 3.4 Infrastructure（基础设施层）

职责：
- `TaskStore`（SQLite/其他 DB）
- `MinifluxGateway`
- `LLMGateway`
- 指标与追踪输出

当前基线：
- 任务主路径采用 `TaskStoreSQLite + claim`，不依赖独立 `QueueAdapter`。

## 4. 任务模型（单一真相源）

推荐 `tasks` 表字段：

- `id`：主键
- `canonical_id`：幂等键（唯一索引）
- `payload_json`：任务输入
- `status`：`pending | running | retryable | dead | done`
- `attempts`：重试次数
- `max_attempts`：最大重试次数
- `next_retry_at`：下次重试时间
- `leased_until`：运行租约过期时间（防止 worker 崩溃后永远卡住）
- `last_error`：最近错误摘要
- `error_key`：归一化错误键（用于失败聚类）
- `trace_id`：可观测关联 ID
- `created_at / updated_at`

建议索引：
- `UNIQUE(canonical_id)`
- `INDEX(status, next_retry_at, leased_until)`
- `INDEX(status, error_key, updated_at)`

## 5. 状态机

```text
pending -> running -> done
                \-> retryable -> pending
                \-> dead
```

规则：
- claim 时原子更新 `pending/retryable -> running`。
- worker 异常退出后，`leased_until` 过期任务可重新 claim。
- 到达 `max_attempts` 后转 `dead`。

## 6. 错误分类与重试

- transient（可重试）：网络超时、上游 5xx、短期限流。
- permanent（不可重试）：参数错误、签名错误、数据结构错误。
- unknown（默认可重试，受 `max_attempts` 限制）。

推荐退避：
- 指数退避 + 抖动，例如 `1s, 2s, 4s, 8s...`，上限 5 分钟。

## 7. 去重策略

1. 主去重：`canonical_id` 唯一约束（持久化层）。
2. 运行时去重：以 `claim` 原子操作为准。
3. 进程内集合去重仅可作为可选性能缓存，不作为正确性依赖。

## 8. 性能策略

1. Worker 常驻线程池，避免每批次重建 `ThreadPoolExecutor`。
2. 批量 claim、批量 ack/状态更新，降低存储 IO 次数。
3. 入口层快速返回，重处理路径全部异步化。
4. 可配置并发参数：
   - `ingest` 接收并发
   - worker 数量
   - 每次 claim 批次大小
   - agent 并发（LLM 并发）

## 9. 可观测性要求

必须有：
- 队列深度（`pending/retryable/running/dead`）
- 处理吞吐（tasks/s）
- 成功率与失败率
- 重试次数分布
- P50/P95/P99 处理时延
- 每个任务的 `trace_id` 全链路日志
- 失败聚类视图（`status + error_key`）与重入队能力

## 10. 推荐目录结构（目标）

```text
app/
  interfaces/
    http/
      webhook_ingest.py
  application/
    ingest_service.py
    worker_service.py
    retry_policy.py
  domain/
    processor.py
    canonical_id.py
    models.py
  infrastructure/
    task_store_sqlite.py
    queue_sqlite.py
    queue_redis.py
    miniflux_gateway.py
    llm_gateway.py
  observability/
    trace.py
    metrics.py
```

## 11. 分阶段迁移（建议顺序）

1. Phase 1：引入 `TaskStore` 与任务状态机（不改现有业务处理逻辑）。
2. Phase 2：webhook 从“入内存队列”改为“持久化任务 + 投递 task_id”。
3. Phase 3：worker 按状态机执行，并接管重试/死信。
4. Phase 4：`process_entry` 收敛为纯处理函数，删除状态编排逻辑。
5. Phase 5：补齐指标与告警，做压力测试和参数调优。

## 12. 当前实现与目标关系

- 当前实现可作为过渡版本（快速可用）。
- 目标架构用于提升：可恢复性、可定位性、多实例扩展能力与性能上限。
- 后续代码变更应优先遵循本文的职责边界与状态机设计。

## 13. 当前实现状态（截至 2026-03-01）

当前仓库已完成持久化任务主链路和最小运维闭环：

- `common/task_store.py`：任务状态常量、`TaskRecord`、`TaskStore` 协议。
- `common/task_store_sqlite.py`：SQLite 任务存储（包含 `error_key` 聚类与重入队能力）。
- `common/task_error_key.py`：错误归一化逻辑（URL/UUID/数字噪声归一化）。
- `core/task_worker.py`：后台 worker（claim -> process -> done/retry/dead）。
- `myapp/webhook_ingest.py`：webhook 主路径仅持久化任务，不回退内存队列/同步处理。
- `myapp/task_query.py`：任务查询、失败分组、批量/单任务重入队 API。
- `debug-ui/index.html`：最小任务排障 UI（失败分组查询 + 样本查看 + 重入队）。

相关测试覆盖：
- `tests/test_task_store_sqlite.py`
- `tests/test_task_worker.py`
- `tests/test_task_query_api.py`

说明：当前实现已移除旧 `WebhookQueue` 在 webhook 主路径上的回退语义，任务正确性以持久化状态为准。
