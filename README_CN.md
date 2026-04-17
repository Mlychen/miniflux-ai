# miniflux-ai
Miniflux with AI

本项目与 Miniflux 集成，通过 API 或 Webhook 获取 RSS 订阅内容。然后利用大语言模型（如 Ollama, ChatGPT, LLaMA, Gemini）生成摘要、翻译和 AI 驱动的新闻洞察。

## 功能特性

- **Miniflux 集成**：无缝获取 Miniflux 未读条目，或通过 Webhook 触发。
- **定时任务**：指定请求 Miniflux API 的时间间隔。
- **LLM 处理**：基于你选择的 LLM Agent 生成摘要、翻译等。
- **AI 新闻**：使用 LLM Agent 从订阅内容生成 AI 早报/晚报。
- **灵活配置**：通过 `config.yml` 轻松修改或添加新的 Agent。
- **Markdown 和 HTML 支持**：根据配置输出 Markdown 或带样式的 HTML 块。

<table>
  <tr>
    <td>
      摘要、翻译
    </td>
    <td>
      AI 新闻
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

## 架构

### 结构

本项目采用基于持久化队列和原子任务认领的任务状态架构：

- **接入层 (`app/interfaces/http/webhook_ingest.py`)**
  - 校验 Webhook，规范化 Payload，持久化任务，仅在写入持久化存储后返回 `202`。
- **Worker 层 (`app/application/worker_service.py`)**
  - 批量认领任务，执行重试策略，最终状态流转为 `done/retryable/dead`。
- **处理层 (`app/domain/processor.py`)**
  - 纯业务逻辑（预处理、Agent 执行、渲染、Miniflux 更新、摘要归档），不涉及队列或状态编排。
- **基础设施层 (`app/infrastructure/*`)**
  - 任务存储、Miniflux 和 LLM 适配器、SQLite 仓储、可观测性集成。

依赖方向：`interface -> application -> domain <- infrastructure`。

详情请参阅 [架构设计](docs/ARCHITECTURE.md)。

### 应用工厂集成

`create_app(...)` 直接接收仓储依赖。在默认的 SQLite 部署中，可以显式注入各类仓储；如果希望 Webhook 请求写入持久化任务队列，则还需要提供 `task_store`：

```python
import threading

from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite
from app.infrastructure.task_store_sqlite import TaskStoreSQLite
from app.interfaces.http import create_app

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
    saved_entries_repository=SavedEntriesRepositorySQLite(
        path="runtime/miniflux_ai.db", lock=shared_lock
    ),
    task_store=TaskStoreSQLite(
        path="runtime/miniflux_ai.db", lock=shared_lock
    ),
)
```

## 文档

- [架构设计](docs/ARCHITECTURE.md)
- [测试指南](docs/TESTING_GUIDE.md)
- [性能分析指南](docs/PROFILING_GUIDE.md)
- [日志过滤指南](docs/LOGGING_FILTER_GUIDE.md)
- [处理链路追踪指南](docs/PROCESS_TRACE_GUIDE.md)
- [Debug UI 指南](docs/debug-ui/README.md)
- [Web UI 接口参考](docs/WEB_UI_API_CN.md)

## 环境要求

- Python 3.11+
- 依赖：通过 `pip install -r requirements.txt` 安装
- Miniflux API Key
- 兼容 OpenAI 格式的 LLM API Key（例如用于 LLaMA 3.1 的 Ollama）

## 配置

项目包含配置模板文件：`config.sample.English.yml` 和 `config.sample.Chinese.yml`。修改 `config.yml` 以设置：

> 如果使用 Webhook，请在 设置 > 集成 > Webhook > Webhook URL 中输入 URL。
> 
> 如果与 Miniflux 部署在同一容器网络中，使用以下 URL：
> http://ai/miniflux-ai/webhook/entries

- **Miniflux**：Base URL、API Key、`entry_mode`、Webhook 密钥以及持久化任务参数。
- **LLM**：模型设置、API Key 和端点。还可以设置 `timeout`, `max_workers`, `RPM`, `daily_limit`, `pool_capacity`, `request_expected_retries`, 和 `request_ttl_seconds`。
- **AI News**：每日新闻生成的定时计划和提示词。
- **Debug**：通过 `debug.enabled`、`debug.host`、`debug.port` 控制调试 HTTP 入口。
- **Agents**：定义每个 Agent 的提示词、allow_list/deny_list 过滤器和输出样式（`style_block` 控制输出是否使用 HTML blockquote 包裹）。

### `config.yml` 示例（已脱敏）

```yaml
log_level: "INFO"

miniflux:
  base_url: https://your-miniflux.example.com
  api_key: YOUR_MINIFLUX_API_KEY
  # auto：有 webhook_secret 时走 webhook，否则走 polling
  entry_mode: auto
  webhook_secret: YOUR_MINIFLUX_WEBHOOK_SECRET
  # 持久化任务处理（Webhook 模式需要任务存储）
  task_workers: 2
  task_claim_batch_size: 20
  task_lease_seconds: 60
  task_poll_interval: 1.0
  task_retry_delay_seconds: 30
  task_max_attempts: 5
  # 可选：启用 save_entry 专用管线（仅入库，不改写条目）
  save_entry_enabled: false
  # 可选：save_entry 任务最大重试次数（未设置时沿用 task_max_attempts）
  save_entry_max_attempts: 5
  # 可选：轮询间隔（分钟）
  schedule_interval: 15

llm:
  base_url: https://api.your-llm-provider.com
  api_key: YOUR_LLM_API_KEY
  model: deepseek-chat
  max_workers: 4
  RPM: 1000
  # 可选
  daily_limit: 10000
  pool_capacity: 2000
  request_expected_retries: 2
  request_ttl_seconds: 600

ai_news:
  url: http://ai

debug:
  enabled: false
  host: 0.0.0.0
  port: 8081
```

运行时行为：

- `miniflux.entry_mode=auto`
  - 配置了 `webhook_secret`：启动 webhook 模式
  - 未配置 `webhook_secret`：启动 polling 模式
- `miniflux.entry_mode=webhook`：启动 Flask + 持久化任务 worker，且要求存在 `webhook_secret`
- `miniflux.entry_mode=polling`：仅启动定时轮询
- 即使条目处理走 polling，只要配置了 `ai_news.schedule` 或 `debug.enabled`，也会启动 Flask HTTP 入口。

Webhook 模式行为：
- `/miniflux-ai/webhook/entries` 总是先持久化到任务存储。
- 如果任务存储未配置/不可用，Webhook 返回 `500`，且不会回退到内存队列/同步处理。
- `event_type=save_entry` 行为：
  - 默认（`save_entry_enabled: false`）：返回 `200`，状态为 `ignored`。
  - 启用（`save_entry_enabled: true`）：入队专用 `save_entry` 任务并返回 `202`。
  - 处理逻辑仅写入 `saved_entries` 表，不会回写 Miniflux 条目内容。

Web UI 与调试接口详情见：

- [Web UI 接口参考](docs/WEB_UI_API_CN.md)

### 工作流程

1. 从模板创建本地配置。
   - 英文：`Copy-Item config.sample.English.yml config.yml`
   - 中文：`Copy-Item config.sample.Chinese.yml config.yml`
2. 仅在本地 `config.yml` 中填写真实凭据（`miniflux.api_key`, `miniflux.webhook_secret`, `llm.api_key`）。
3. 根据你的用例调整 `ai_news.prompts` 和 `agents.allow_list/deny_list`。
4. 运行前验证配置加载：
   - `uv run python -c "from main import bootstrap; bootstrap('config.yml'); print('bootstrap ok')"`
5. 运行应用：
   - `uv run python main.py`
6. 分享/调试时，使用已脱敏的文件（`config.redacted.yml`），切勿发布 `config.yml`。

数据持久化使用 `runtime/miniflux_ai.db` 作为单一真相源。

当前主要 SQLite 表职责如下：

- `tasks`：Webhook 持久化任务队列与重试状态存储
- `entries`：供 `generate_daily_news()` 消费的临时摘要队列
- `saved_entries`：`save_entry` Webhook 事件的持久化结果
- `summary_archive`：用于后续分析与回填的持久化摘要归档
- `ai_news`：供 RSS 输出消费的最新 AI News 内容

## Docker 部署

仓库已经提供完整的 `docker-compose.yml` 本地栈，当前包含：

- `db`：Miniflux 使用的 PostgreSQL
- `app`：Miniflux 主服务
- `ai`：本项目服务（`ghcr.io/qetesh/miniflux-ai:latest`）
- `rss-bridge`：可选 RSS Bridge 服务

其中 `ai` 服务挂载：

- `./config.yml:/app/config.yml`
- `./runtime:/app/runtime`

所有服务都加入同一个 `miniflux-net` bridge 网络，因此 Webhook 和 AI News URL 可以直接使用容器名，例如 `http://ai/miniflux-ai/webhook/entries`。

参考 `config.sample.*.yml` 创建 `config.yml`，然后启动整套服务：

```bash
docker compose up -d
```

## 使用方法

1. 确保 `config.yml` 已正确配置。
2. 运行脚本：`python main.py`
3. 条目处理方式取决于 `miniflux.entry_mode`：
   - `polling`：调度器主动抓取 Miniflux 未读条目，使用 LLM 处理，并回写 Miniflux 内容。
   - `webhook`：应用等待 `/miniflux-ai/webhook/entries` 请求，先持久化任务，再由 durable worker 异步处理。
   - `auto`：有 `webhook_secret` 时等同于 `webhook`，否则等同于 `polling`。
4. 如果配置了 `ai_news.schedule`，调度器还会生成 AI News 并刷新 `/miniflux-ai/rss/ai-news`。
5. 如果 `debug.enabled` 为 `true`，HTTP 应用还会提供 Debug UI 和调试接口。

## 开发与测试

### 使用 uv（推荐）

1. 创建虚拟环境：`uv venv .venv`
2. 安装依赖：`uv pip install -r requirements-dev.txt`
3. 运行测试：
   `uv run pytest tests/`
4. 运行 lint：`uv run ruff check .`
5. 运行 typecheck：`uv run mypy --ignore-missing-imports .`
6. 运行应用：`uv run python main.py`

### 使用 pip（替代方案）

1. 安装开发依赖：`pip install -r requirements-dev.txt`
2. 运行测试：
   `pytest tests/`
3. 运行 lint：`ruff check .`
4. 运行 typecheck：`mypy --ignore-missing-imports .`

## FAQ
<details>
<summary>如果摘要内容格式不正确，请在 设置 > 自定义 CSS 中添加以下代码：</summary>
```
pre code {
    white-space: pre-wrap;
    word-wrap: break-word;
}
```
</details>

## 贡献

欢迎 Fork 本仓库并提交 Pull Requests。欢迎提交贡献和 Issue！

## 变更日志

- 参见 `CHANGELOG.md` 了解 API 和分层变更。

## 许可证

本项目基于 MIT 许可证开源。
