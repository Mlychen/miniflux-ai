# Testing Guide

This is the single entry point for test execution, live verification, and LLM test prompts.

## 1) Local Unit Modules

### filter

- Scope: feed filtering and duplicate-guard behavior.
- Command:
  - `uv run pytest tests/unit/test_filter.py`

### config

- Scope: config parsing from dict/file and key mapping.
- Command:
  - `uv run pytest tests/unit/test_config.py`

### integrity

- Scope:
  - SQLite 仓储一致性（processed records / summaries）
  - idempotent skip for processed entries
  - AI news generation and cleanup consistency
- Command:
  - `uv run pytest tests/unit/test_data_integrity.py`

### webhook-api

- Scope: webhook signature validation and API status-code contract.
- Command:
  - `uv run pytest tests/integration/test_webhook_api.py`

### task-store-sqlite

- Scope:
  - durable task state machine (`pending/running/retryable/dead/done`)
  - claim lease/retry/requeue behavior
  - failure-group aggregation and normalized `error_key`
- Command:
  - `uv run pytest tests/unit/test_task_store_sqlite.py`

### task-worker

- Scope:
  - worker claim-process-mark loop
  - retryable vs dead transition behavior
  - runtime stop and polling behavior
- Command:
  - `uv run pytest tests/unit/test_task_worker.py`

### task-query-api

- Scope:
  - `/miniflux-ai/user/tasks*` observability and requeue endpoints
  - pagination/filter validation and error contracts
- Command:
  - `uv run pytest tests/integration/test_task_query_api.py`

### concurrency

- Scope:
  - concurrent repository write integrity
  - batch fetch path processes each unread entry
- Command:
  - `uv run pytest tests/integration/test_concurrency_integrity.py`

### ai-news-api

- Scope: `/miniflux-ai/rss/ai-news` output and AI news repository consume-and-clear behavior.
- Command:
  - `uv run pytest tests/integration/test_ai_news_api.py`

### batch-usecase

- Scope:
  - shared batch-processing orchestration for polling and webhook paths
  - failure aggregation behavior in concurrent execution
- Command:
  - `uv run pytest tests/unit/test_batch_usecase.py`

### service-containers

- Scope:
  - typed Flask service container (`AppServices`)
  - typed bootstrap runtime container (`RuntimeServices`)
- Command:
  - `uv run pytest tests/unit/test_service_containers.py`

### adapters

- Scope:
  - Miniflux gateway call delegation
  - LLM gateway provider-specific request building
- Command:
  - `uv run pytest tests/unit/test_adapters.py`

### core-helpers

- Scope:
  - entry rendering helpers
  - AI news composition and feed-matching helpers
- Command:
  - `uv run pytest tests/unit/test_core_helpers.py`

### ai-news-repository-sqlite

- Scope:
  - SQLite `ai_news` repository save/consume semantics
- Command:
  - `uv run pytest tests/unit/test_ai_news_repository_sqlite.py`

### entries-repository-sqlite

- Scope:
  - SQLite `entries` repository append/read/clear semantics
- Command:
  - `uv run pytest tests/unit/test_entries_repository_sqlite.py`

### unit-all

- Scope: all local unit modules.
- Command:
  - `uv run pytest tests/unit/`

### lint

- Scope: code style and static issues.
- Command:
  - `uv run ruff check .`

### typecheck

- Scope: static type consistency.
- Command:
  - `uv run mypy --ignore-missing-imports .`

## 2) Live Integration Flow

1. Bootstrap:
   - `uv run python -c "from main import bootstrap; s=bootstrap('config.yml'); print('bootstrap ok')"`
2. Miniflux connectivity:
   - `uv run python -c "import miniflux; from common.config import Config; c=Config.from_file('config.yml'); cli=miniflux.Client(c.miniflux_base_url, api_key=c.miniflux_api_key); print(cli.me().get('username'))"`
3. Webhook checks:
    - invalid signature -> expect `403`
    - valid signature -> expect `202` (accepted only after durable task persistence)
4. Polling check:
   - one `fetch_unread_entries(...)` run
5. AI News check:
   - one `generate_daily_news(...)` run
  - `GET /miniflux-ai/rss/ai-news` returns content

For release gating and 24h observation criteria, use:

- `ROLLOUT_CHECKLIST.md`

## 3) End-to-End 测试流程（Miniflux + LLM）

> 目标：在连上真实 Miniflux 和 LLM 的环境下，从入口到 AI News 输出进行一次完整验证（可用于人工测试或“编程 LLM”执行 e2e 检查）。
>
> 调试工具：
> - **Browser-Use**: 如需在受限环境（如 Trae IDE、Docker）中使用 `browser-use` 进行自动化测试或调试，请参考 [BrowseUse_Guide.md](docs/BrowseUse_Guide.md)。该文档提供了解决沙箱权限和路径问题的标准代码范例。
>
> 前提：
> - `config.yml` 已配置真实 `miniflux.base_url` / `miniflux.api_key`
> - `llm` 段已配置可用的 provider / api_key / model
> - 推荐将 `log_level` 临时设置为 `DEBUG` 便于观测

1. 启动应用
   - 轮询或 webhook 入口根据 `miniflux.entry_mode` 自动决定：
     - `webhook` 或 `auto`+有 `webhook_secret`：仅启动 webhook（Flask + durable task worker）
     - `polling`：仅启动轮询
   - 本地/服务器启动命令示例：
     - `uv run python main.py *>> .\miniflux-ai.log`

2. Miniflux 连接与入口校验
   - 运行 Live Integration Flow 中的：
     - bootstrap 检查
     - Miniflux `me()` 检查
   - webhook 模式下：
     - 在 Miniflux 后台配置 Webhook URL：`<your-base-url>/miniflux-ai/webhook/entries`
     - 使用有效/无效签名请求校验 `403 / 202` 行为（可通过测试或手工 curl）

3. 条目处理链路
   - 轮询模式：触发一次 `fetch_unread_entries(...)`（或等待 schedule）
   - webhook 模式：通过 Miniflux 或模拟请求推送一批 entries
   - 期望行为：
     - 新条目进入处理（可通过日志中 `process_entry:` 前缀和 `agents:` 日志确认）
     - 重复条目被去重跳过（带 dedup marker 或已在 processed records 中）

4. AI News 生成与 RSS 校验
   - 如果配置了 `ai_news.schedule`，等待其中一个时间点触发；否则可手动调用：
     - `generate_daily_news(miniflux_client, config, llm_client, logger, ai_news_repository, entries_repository)`
   - 检查：
     - 日志中出现 `Generating daily news` 与 `Generated daily news successfully`
      - AI news 写入并在 `/miniflux-ai/rss/ai-news` 被消费清空
     - 浏览器或 curl 访问：`GET /miniflux-ai/rss/ai-news` 返回包含：
       - `<rss` 及 “Powered by miniflux-ai”
       - 基于当日内容生成的 AI News 条目

5. 日志与 24h 灰度观察
   - 使用 `LOGGING_FILTER_GUIDE.md` 中的过滤建议分析：
     - 入口负载（轮询 + webhook）
     - 队列健康度
     - entry 处理与去重效果
     - LLM 调用错误与输出长度
     - AI News 触发节奏与产出体量
   - 对于正式发布前的 24h 灰度期，参见：
     - `ROLLOUT_CHECKLIST.md` 中的 “24h Gray Observation” 小节

> 编程 LLM 提示：如需自动化执行 e2e 流程，可结合本小节与 “Live Integration Flow” 步骤，按顺序调用 bootstrap / Miniflux 检查 / webhook 或 polling / generate_daily_news / RSS 检查，并基于日志关键字给出 GO / NO-GO 结论。

## 4) LLM Prompt Templates

### Prompt A: Run one module

```text
Run miniflux-ai test module: {filter|config|integrity|webhook-api|task-store-sqlite|task-worker|task-query-api|concurrency|ai-news-api|batch-usecase|service-containers|adapters|core-helpers|ai-news-repository-sqlite|entries-repository-sqlite}.
Use uv commands.
Do not modify code.
Return:
1) command used
2) pass/fail
3) failed test names
4) shortest fix action
```

### Prompt B: Run full unit baseline

```text
Run:
uv run pytest tests/unit/

Return:
1) summary counts
2) failures with file::test
3) release risk level (low/medium/high)
```

### Prompt C: Run live smoke

```text
Validate miniflux-ai live path with current config.yml:
1) bootstrap check
2) Miniflux me() check
3) webhook invalid signature -> expect 403
4) webhook valid signature -> expect 202
5) one polling run
6) daily news generation + rss check

Return final gate: GO or NO-GO.
```

### Prompt D: Integrity focus

```text
Run integrity-focused validation for miniflux-ai.
Required:
- tests/unit/test_data_integrity.py
- one live generate_daily_news run (if config is available)

Evaluate:
1) entries repository lifecycle
2) ai_news repository lifecycle
3) duplicate-processing risk
4) concurrency/file-lock risk

Return:
- findings ordered by severity
- concrete remediation list
```

## 5) Skill Shortcut

Run module tests through skill script:

- `powershell -NoProfile -ExecutionPolicy Bypass -File .sisyphus/run-continuation/miniflux-test-modules/scripts/run-module-tests.ps1 -Module unit-all`
