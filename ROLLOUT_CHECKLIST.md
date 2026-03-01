# Rollout Checklist（Task 架构）

## 1) Pre-flight

1. 创建环境：
   - `uv venv .venv`
2. 安装依赖：
   - `uv pip install -r requirements-dev.txt`
3. 运行全量回归：
   - `uv run python -m unittest discover -q tests`
4. 关键模块最小回归（可选快速）：
   - `uv run python -m unittest -q tests.test_task_store_sqlite tests.test_task_worker tests.test_task_query_api tests.test_webhook_api`

## 2) Runtime Smoke Test

1. 配置检查：
   - `uv run python -c "from main import bootstrap; bootstrap('config.yml'); print('bootstrap ok')"`
2. 启动服务：
   - `uv run python main.py`
3. 启动后日志应出现：
   - `Successfully connected to Miniflux!`
   - `TaskWorker.start:`

## 3) Functional Checks

1. Webhook 路径：
   - 无效签名请求返回 `403`
   - 有效签名请求返回 `202`
   - 返回体含 `status=accepted` 和 `accepted/duplicates`
2. 任务可观测接口：
   - `GET /miniflux-ai/user/tasks/metrics` 返回 `status=ok`
   - `GET /miniflux-ai/user/tasks/failure-groups` 返回 `status=ok`
3. Debug UI 排障面板：
   - `GET /debug/` 可访问
   - 分组查询、样本查询、重入队动作可用

## 4) 24h Observation

1. 关注 worker 错误：
   - `TaskWorker.claim_tasks error=`
   - `TaskWorker.task_result ... status=retryable|dead`
2. 关注 webhook 持久化错误：
   - `Webhook task persistence failed`
3. 关注失败分组趋势：
   - `failure-groups` 中是否出现持续增长的同类 `error_key`

## 5) Release Gate

满足以下条件再发布：

1. 全量测试通过。
2. Webhook `403/202` 契约正确。
3. Task metrics/failure-groups 接口稳定。
4. 无持续异常增长的 `dead` 任务分组。
