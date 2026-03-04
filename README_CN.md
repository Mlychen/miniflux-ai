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

- **接入层 (`myapp/webhook_ingest.py`)**
  - 校验 Webhook，规范化 Payload，持久化任务，仅在写入持久化存储后返回 `202`。
- **Worker 层 (`core/task_worker.py`)**
  - 批量认领任务，执行重试策略，最终状态流转为 `done/retry/dead`。
- **处理层 (`core/process_entries.py`)**
  - 纯业务逻辑（预处理、Agent 执行、渲染、源更新），不涉及队列/状态编排。
- **基础设施层 (`common/*`, `adapters/*`)**
  - 任务存储、Miniflux 和 LLM 适配器、可观测性集成。

依赖方向：`interface -> application -> domain <- infrastructure`。

详情请参阅 [架构设计](docs/ARCHITECTURE.md)。

### 应用工厂集成

`create_app(...)` 直接接收仓储依赖。典型集成方式（SQLite，默认）：

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
> http://miniflux_ai/miniflux-ai/webhook/entries

- **Miniflux**：Base URL 和 API Key。
- **LLM**：模型设置、API Key 和端点。还可以设置 `timeout`, `max_workers`, `RPM`, `daily_limit`, `pool_capacity`, `request_expected_retries`, 和 `request_ttl_seconds`。
- **AI News**：每日新闻生成的定时计划和提示词。
- **Agents**：定义每个 Agent 的提示词、allow_list/deny_list 过滤器和输出样式（`style_block` 控制输出是否使用 HTML blockquote 包裹）。

### `config.yml` 示例（已脱敏）

```yaml
log_level: "INFO"

miniflux:
  base_url: https://your-miniflux.example.com
  api_key: YOUR_MINIFLUX_API_KEY
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
  url: http://miniflux_ai
```

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

## Docker 部署

项目包含 `docker-compose.yml` 文件以便轻松部署：

> 如果使用 Webhook 或 AI 新闻，建议与 Miniflux 使用同一个 docker-compose.yml 并通过容器名称访问。

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
            # 持久化 SQLite DB
            - ./runtime:/app/runtime

```
参考 `config.sample.*.yml` 创建 `config.yml`。
启动服务：

```bash
docker-compose up -d
```

## 使用方法

1. 确保 `config.yml` 已正确配置。
2. 运行脚本：`python main.py`
3. 脚本将获取未读 RSS 条目，使用 LLM 处理，并在 Miniflux 中更新内容。

## 开发与测试

### 使用 uv（推荐）

1. 创建虚拟环境：`uv venv .venv`
2. 安装依赖：`uv pip install -r requirements-dev.txt`
3. 运行测试：
   `uv run pytest --cov=core --cov=adapters --cov=myapp tests/`
4. 运行 lint：`uv run ruff check .`
5. 运行 typecheck：`uv run mypy --ignore-missing-imports .`
6. 运行应用：`uv run python main.py`

### 使用 pip（替代方案）

1. 安装开发依赖：`pip install -r requirements-dev.txt`
2. 运行测试：
   `pytest --cov=core --cov=adapters --cov=myapp tests/`
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
