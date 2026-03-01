# 持久化任务架构实施方案（冻结版）

> 状态：Frozen v1（执行中，Phase C 已完成最小交付）  
> 日期：2026-03-01  
> 目标：以“可读性、可扩展、性能优先”为原则，将 webhook 处理主链路迁移到持久化任务模型。

---

## 1. 固定决策（不再反复讨论）

1. 交付语义：`at-least-once` + 幂等（`canonical_id` 唯一）。
2. 入站语义：`202` 仅表示“已持久化接收”，不表示处理完成。
3. 主状态机：`pending -> running -> done`，失败流转 `retryable/dead`。
4. 主队列实现：当前阶段使用 SQLite `tasks` 表 + worker claim。
5. 兼容策略：不保留旧 `WebhookQueue` 回退路径，webhook 仅走持久化任务主链路。
6. 正确性优先级：持久化状态 > 进程内内存状态。

---

## 2. 当前代码基线（已完成）

1. 任务协议与模型：
   - `common/task_store.py`
2. SQLite 任务存储：
   - `common/task_store_sqlite.py`
3. 后台 worker：
   - `core/task_worker.py`
4. webhook 持久化入站：
   - `myapp/webhook_ingest.py`（优先走 `TASK_STORE`）
5. 启动接线：
   - `main.py`（webhook 模式仅启动 `TaskWorker`）
6. 应用容器注入：
   - `myapp/__init__.py`
   - `myapp/services.py`
7. 配置项：
   - `common/config.py` 增加 `task_*` 参数

---

## 3. 阶段计划（执行顺序固定）

## Phase A：稳定化（当前阶段，必须先完成）

状态：已完成

目标：确认“持久化入站 + claim + done/retry/dead”行为稳定。

任务：
1. 固定错误分类边界：
   - `PermanentTaskError`：参数/数据不可恢复错误 -> `dead`
   - 其余异常：默认 `retryable`
2. 统一 webhook 入站返回体：
   - `status`, `accepted`, `duplicates`, `trace_id(optional)`
3. 统一 worker 日志字段：
   - `task_id`, `canonical_id`, `attempts`, `status`, `error`

验收标准：
1. webhook 与 worker 相关单测全部通过。
2. 在重复 webhook 场景下，无重复任务行（`canonical_id` 唯一）。
3. 任务失败后可重试；不可恢复错误转 `dead`。

---

## Phase B：处理链收敛

状态：已完成

目标：降低漏处理风险，避免“预标记后失败”。

任务：
1. 将 in-memory `try_mark` 去重从“正确性依赖”降级为“可选缓存”。
2. 处理成功后再写最终处理标记；失败不写成功标记。
3. 明确 `process_entry` 的失败契约（哪些错误抛出，哪些吞掉并记录）。

验收标准：
1. 失败任务不会被提前判定为“已处理完成”。
2. 相同输入在重试后可继续被处理。
3. `process_entries_batch` failure 统计与任务状态一致。

---

## Phase C：可观测性与运维接口

目标：让状态可查、问题可定位。

任务：
1. 新增任务查询接口（只读）：
   - `GET /miniflux-ai/user/tasks?status=&limit=&offset=&include_payload=`
   - `GET /miniflux-ai/user/tasks/<task_id>`
2. 增加关键指标输出：
   - `GET /miniflux-ai/user/tasks/metrics?window_seconds=`
   - 覆盖队列水位、吞吐、失败率、重试压力、积压时延
3. 增加失败聚合与重入队接口：
   - `GET /miniflux-ai/user/tasks/failure-groups`
   - `GET /miniflux-ai/user/tasks/failure-groups/tasks`
   - `POST /miniflux-ai/user/tasks/failure-groups/requeue`
   - `POST /miniflux-ai/user/tasks/<task_id>/requeue`
   - `POST /miniflux-ai/user/tasks/requeue`
4. 提供最小 Debug UI 排障面板（失败分组查询/样本查看/重入队）。

验收标准：
1. 可通过 API 观察任务队列水位与失败原因。
2. 日志和任务状态可相互关联（`trace_id` / `task_id`）。

状态：已完成（API + Debug UI 最小闭环）

---

## Phase D：回退路径下线（最后执行）

目标：删除旧 `WebhookQueue` 主路径依赖。

任务：
1. 确认 task 模式在常规场景稳定后，移除旧队列路径。
2. 清理旧路径相关冗余逻辑和测试。
3. 更新 README 与迁移说明。

验收标准：
1. 主路径仅保留 task store + worker。
2. 回归测试无功能回退。

状态：已完成（webhook 主链路不再回退内存队列）

---

## 4. 配置策略（冻结）

关键配置（`miniflux`）：
1. `task_store_enabled`（默认 `true`）
2. `task_workers`（默认 `2`）
3. `task_claim_batch_size`（默认 `20`）
4. `task_lease_seconds`（默认 `60`）
5. `task_poll_interval`（默认 `1.0`）
6. `task_retry_delay_seconds`（默认 `30`）
7. `task_max_attempts`（默认 `5`）

禁改原则：
1. 默认值可在后续版本迭代，但变更必须更新本方案文档和 README。

---

## 5. 回滚与应急（冻结）

1. 功能开关回滚：
   - webhook 模式不提供 `WebhookQueue` 回退；应急时改用 `entry_mode: polling`。
2. 数据安全：
   - `tasks` 表只追加状态流转，不做 destructive migration。
3. 异常降级：
   - 持久化失败返回 `500 task persistence failed`，不做假成功 `202`。

---

## 6. 测试门槛（每阶段必须满足）

最小回归集：
1. `tests.test_task_store_sqlite`
2. `tests.test_task_worker`
3. `tests.test_task_query_api`
4. `tests.test_webhook_api`
5. `tests.test_service_containers`
6. `tests.test_data_integrity`
7. `tests.test_concurrency_integrity`

建议命令：
```bash
uv run python -m unittest -q \
  tests.test_task_store_sqlite \
  tests.test_task_worker \
  tests.test_task_query_api \
  tests.test_webhook_api \
  tests.test_service_containers \
  tests.test_data_integrity \
  tests.test_concurrency_integrity
```

---

## 7. 与蓝图文档关系

1. 本文档是执行计划（what/when/how）。
2. `docs/ARCHITECTURE_BLUEPRINT.md` 是目标原则与长期方向（why）。
3. 若两者冲突，以本文档（冻结版）为当前迭代执行依据。
