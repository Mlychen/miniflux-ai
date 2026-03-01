# miniflux-ai
Miniflux with AI

This project integrates with Miniflux to fetch RSS feed content via API or webhook. It then utilizes large language models (e.g., Ollama, ChatGPT, LLaMA, Gemini) to generate summaries, translations, and AI-driven news insights.

## Features

- **Miniflux Integration**: Seamlessly fetch unread entries from Miniflux or trigger via webhook.
- **Schedule Interval**: Specifies the time interval for requesting the miniflux api.
- **LLM Processing**: Generate summaries, translations, etc. based on your chosen LLM agent.
- **AI News**: Use the LLM agent to generate AI morning and evening news from feed content.
- **Flexible Configuration**: Easily modify or add new agents via the `config.yml` file.
- **Markdown and HTML Support**: Outputs in Markdown or styled HTML blocks, depending on configuration.

<table>
  <tr>
    <td>
      summaries, translations
    </td>
    <td>
      AI News
    </td> 
  </tr>
  <tr>
    <td> 
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/11c208d9-816a-4c8c-bc00-2f780529e58d">
        <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/c97e2774-ec10-4acb-bef7-25cf8d43da15">
        <img alt="miniflux AI summaries translations" src="https://github.com/user-attachments/assets/c97e2774-ec10-4acb-bef7-25cf8d43da15" width="400" > 
      </picture>
    </td>
    <td> 
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/b40f5bdd-d265-4beb-a14c-d39d6624760b">
        <source media="(prefers-color-scheme: light)" srcset="https://github.com/user-attachments/assets/e5985025-15f3-43b0-982b-422575962783">
        <img alt="miniflux AI summaries translations" src="https://github.com/user-attachments/assets/e5985025-15f3-43b0-982b-422575962783" width="400" > 
      </picture>
    </td>
  </tr>
</table>

## Architecture

### Current Structure

- **Gateway layer (`adapters/`)**
  - Encapsulates Miniflux and LLM vendor APIs behind stable protocols.
- **Usecase layer (`core/`)**
  - Implements polling, webhook batch processing, summary generation, and AI news workflows.
- **Repository layer (`common/*_repository*.py`)**
  - Persists summaries and AI news in SQLite (`runtime/miniflux_ai.db`) using WAL and batch writes.
- **Application wiring (`main.py`, `myapp/`)**
  - Composes gateways + repositories and injects them into usecases/routes.

Current dependency direction: `gateway -> usecase -> repository` (runtime wiring done at app/bootstrap boundary).

### Target Blueprint (Readability + Extensibility + Performance)

The project is moving toward a task-state architecture with a persistent queue and atomic task claiming:

- **Ingest layer (`myapp/webhook_ingest.py`)**
  - Validate webhook, normalize payload, persist task, return `202` only after durable write.
- **Worker layer (`application/worker`)**
  - Claim tasks in batches, process with retry policy, finalize to `done/retry/dead`.
- **Processor layer (`domain/processor`)**
  - Pure business logic only (preprocess, agents, rendering, source update), no queue/state orchestration.
- **Infrastructure layer (`infrastructure/*`)**
  - Task store, Miniflux and LLM adapters, observability integration.

Target dependency direction: `interface -> application -> domain <- infrastructure`.

For details, see [`docs/ARCHITECTURE_BLUEPRINT.md`](docs/ARCHITECTURE_BLUEPRINT.md).
Implementation baseline (frozen): [`docs/plans/2026-03-01-persistent-task-implementation-plan.md`](docs/plans/2026-03-01-persistent-task-implementation-plan.md).

### App Factory Integration

`create_app(...)` now takes repository dependencies directly. Typical integration (SQLite, default):

```python
import threading

from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.entries_repository_sqlite import EntriesRepositorySQLite
from myapp import create_app

shared_lock = threading.Lock()
app = create_app(
    config=config,
    miniflux_client=miniflux_client,
    llm_client=llm_client,
    logger=logger,
    entry_processor=entry_processor,
    entries_repository=EntriesRepositorySQLite(
        path="runtime/miniflux_ai.db", lock=shared_lock
    ),
    ai_news_repository=AiNewsRepositorySQLite(
        path="runtime/miniflux_ai.db", lock=shared_lock
    ),
)
```

Runtime persistence is SQLite-only in current architecture.

## Requirements

- Python 3.11+
- Dependencies: Install via `pip install -r requirements.txt`
- Miniflux API Key
- API Key compatible with OpenAI-compatible LLMs (e.g., Ollama for LLaMA 3.1)

## Configuration

The repository includes template configuration files: `config.sample.English.yml` and `config.sample.Chinese.yml`. Modify `config.yml` to set up:

> If using a webhook, enter the URL in Settings > Integrations > Webhook > Webhook URL.
> 
> If deploying in a container alongside Miniflux, use the following URL:
> http://miniflux_ai/miniflux-ai/webhook/entries.

- **Miniflux**: Base URL and API key.
- **LLM**: Model settings, API key, and endpoint. You can also set `timeout`, `max_workers`, `RPM`, `daily_limit`, `pool_capacity`, `request_expected_retries`, and `request_ttl_seconds`.
- **AI News**: Schedule and prompts for daily news generation
- **Agents**: Define each agent's prompt, allow_list/deny_list filters, and output style（`style_block` controls whether the output uses an HTML blockquote wrapper）.

### `config.yml` Sample (Sanitized)

```yaml
log_level: "INFO"

miniflux:
  base_url: https://your-miniflux.example.com
  api_key: YOUR_MINIFLUX_API_KEY
  webhook_secret: YOUR_MINIFLUX_WEBHOOK_SECRET
  # durable task processing (webhook mode requires task store)
  task_workers: 2
  task_claim_batch_size: 20
  task_lease_seconds: 60
  task_poll_interval: 1.0
  task_retry_delay_seconds: 30
  task_max_attempts: 5

llm:
  base_url: https://api.your-llm-provider.com
  api_key: YOUR_LLM_API_KEY
  model: deepseek-chat
  max_workers: 4
  RPM: 1000
  # optional
  daily_limit: 10000
  pool_capacity: 2000
  request_expected_retries: 2
  request_ttl_seconds: 600

ai_news:
  url: http://miniflux_ai
```

Webhook mode behavior:
- `/miniflux-ai/webhook/entries` always persists to task store first.
- If task store is not configured/available, webhook returns `500` and does not fall back to in-memory queue/synchronous processing.

Task observability APIs:
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

Debug UI:
- Enable `debug_enabled: true`, then open `/debug/`.
- `任务排障` 面板支持最小闭环：
  - 查询失败分组：`GET /miniflux-ai/user/tasks/failure-groups`
  - 查看分组任务样本：`GET /miniflux-ai/user/tasks/failure-groups/tasks`
  - 查询任务详情：`GET /miniflux-ai/user/tasks/<task_id>`
  - 按筛选批量重入队：`POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - 分组重入队：`POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - 单任务重入队：`POST /miniflux-ai/user/tasks/<task_id>/requeue`
- 该面板用于快速定位失败热点（`status + error_key`）并执行人工重试。

### Working Method

1. Create local config from sample.
   - English: `Copy-Item config.sample.English.yml config.yml`
   - Chinese: `Copy-Item config.sample.Chinese.yml config.yml`
2. Fill only your local `config.yml` with real credentials (`miniflux.api_key`, `miniflux.webhook_secret`, `llm.api_key`).
3. Adjust `ai_news.prompts` and `agents.allow_list/deny_list` for your own use case.
4. Validate config loading before running:
   - `uv run python -c "from main import bootstrap; bootstrap('config.yml'); print('bootstrap ok')"`
5. Run app:
   - `uv run python main.py`
6. For sharing/debugging, use a redacted file (`config.redacted.yml`) and never publish `config.yml`.

Data persistence uses `runtime/miniflux_ai.db` as the single source of truth.


## Docker Setup

The project includes a `docker-compose.yml` file for easy deployment:

> If using webhook or AI news, it is recommended to use the same docker-compose.yml with miniflux and access it via container name.

```yaml
services:
    miniflux_ai:
        container_name: miniflux_ai
        image: ghcr.io/qetesh/miniflux-ai:latest
        restart: unless-stopped
        environment:
            TZ: Asia/Shanghai
        volumes:
            - ./config.yml:/app/config.yml
            # Persist SQLite DB
            - ./runtime:/app/runtime

```
Refer to `config.sample.*.yml`, create `config.yml`
To start the services:

```bash
docker-compose up -d
```

## Usage

1. Ensure `config.yml` is properly configured.
2. Run the script: `python main.py`
3. The script will fetch unread RSS entries, process them with the LLM, and update the content in Miniflux.

## Development and Tests

### Use uv (recommended)

1. Create virtual environment: `uv venv .venv`
2. Install dependencies: `uv pip install -r requirements-dev.txt`
3. Run unit tests:
   `uv run python -m unittest discover -q tests`
4. Run app: `uv run python main.py`

### Use pip (alternative)

1. Install development dependencies: `pip install -r requirements-dev.txt`
2. Run unit tests:
   `python -m unittest discover -q tests`
3. Optional: run `pytest -q` if you prefer pytest runner.

## Testing Modules and Skill

1. Unified testing guide: `TESTING_GUIDE.md`
2. Reusable skill package:
   - `.sisyphus/run-continuation/miniflux-test-modules/SKILL.md`
3. Run the skill script directly:
   - `powershell -NoProfile -ExecutionPolicy Bypass -File .sisyphus/run-continuation/miniflux-test-modules/scripts/run-module-tests.ps1 -Module unit-all`

## Roadmap
- [x] Add daily summary(by title, Summary of existing AI)
  - [x] Add Morning and Evening News（e.g. 9/24: AI Morning News, 9/24: AI Evening News）
  - [x] Add timed summary

## FAQ
<details>
<summary>If the formatting of summary content is incorrect, add the following code in Settings > Custom CSS:</summary>
```
pre code {
    white-space: pre-wrap;
    word-wrap: break-word;
}
```
</details>

## Contributing

Feel free to fork this repository and submit pull requests. Contributions and issues are welcome!

## Changelog

- See `CHANGELOG.md` for API and layering changes.

<a href="https://github.com/Qetesh/miniflux-ai/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Qetesh/miniflux-ai" />
</a>


## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Qetesh/miniflux-ai&type=Date)](https://star-history.com/#Qetesh/miniflux-ai&Date)

## License

This project is licensed under the MIT License.
