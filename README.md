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

- **Gateway layer (`adapters/`)**
  - Encapsulates Miniflux and LLM vendor APIs behind stable protocols.
- **Usecase layer (`core/`)**
  - Implements polling, webhook batch processing, summary generation, and AI news workflows.
- **Repository layer (`common/*_repository.py`)**
  - Handles JSON persistence (`entries.json`, `ai_news.json`) with lock-safe operations.
- **Application wiring (`main.py`, `myapp/`)**
  - Composes gateways + repositories and injects them into usecases/routes.

Dependency direction: `gateway -> usecase -> repository` (runtime wiring done at app/bootstrap boundary).

### App Factory Integration

`create_app(...)` now takes repository dependencies directly. Typical integration:

```python
import threading

from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from myapp import create_app

shared_lock = threading.Lock()
app = create_app(
    config=config,
    miniflux_client=miniflux_client,
    llm_client=llm_client,
    logger=logger,
    entry_processor=entry_processor,
    entries_repository=EntriesRepository(path='entries.json', lock=shared_lock),
    ai_news_repository=AiNewsRepository(path='ai_news.json', lock=shared_lock),
)
```

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
- **LLM**: Model settings, API key, and endpoint. You can also set `timeout` and `max_workers` for multithreading.
- **AI News**: Schedule and prompts for daily news generation
- **Agents**: Define each agent's prompt, allow_list/deny_list filters, and output style（`style_block` controls whether the output uses an HTML blockquote wrapper）.

### `config.yml` Sample (Sanitized)

```yaml
log_level: "INFO"

miniflux:
  base_url: https://your-miniflux.example.com
  api_key: YOUR_MINIFLUX_API_KEY
  webhook_secret: YOUR_MINIFLUX_WEBHOOK_SECRET

llm:
  base_url: https://api.your-llm-provider.com
  api_key: YOUR_LLM_API_KEY
  model: deepseek-chat

ai_news:
  url: http://miniflux_ai
```

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
            # - ./entries.json:/app/entries.json # Provide persistent for AI news

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
   `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`
4. Run app: `uv run python main.py`

### Use pip (alternative)

1. Install development dependencies: `pip install -r requirements-dev.txt`
2. Run unit tests:
   `python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`
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
