## 阶段 0：基线校准

### 1. 目标

- 固定当前行为基线，为后续重构提供回归参照。
- 确认现有 AI News 和 entries/ai_news 持久化在测试层面是“绿”的。

### 2. 修改范围

- 不修改任何代码。
- 仅梳理和固化测试命令与关键用例，作为后续阶段的对照组。

### 3. 现有数据结构

- `entries.json`（通过 `EntriesRepository` 写入），单条记录结构：

  ```json
  {
    "datetime": "entry.created_at",
    "category": "entry.feed.category.title",
    "title": "entry.title",
    "content": "agent 响应内容（HTML/Markdown）",
    "url": "entry.url"
  }
  ```

- `ai_news.json`（通过 `AiNewsRepository` 写入），内容：
  - 单个字符串，对应当次 AI News 的 Markdown。

### 4. 现有数据流

- 入口（轮询或 webhook）：
  - Miniflux → `fetch_unread_entries` 或 webhook → `process_entry`
  - `process_entry`：
    - 调用各类 agent 生成摘要/翻译。
    - 通过 `EntriesRepository.append_summary_item` 将条目写入 `entries.json` 列表。

- AI News：
  - `generate_daily_news`：
    - 从 `entries.json` 读取所有条目。
    - 将每条的 `content` 简单拼接为一个大文本。
    - 顺序调用 LLM：
      - greeting：基于当前时间生成开场白。
      - summary_block：基于拼接内容生成“深度情报简报”。
      - summary：基于 summary_block 生成“管理层摘要”。
    - 使用 `compose_daily_news_content` 合成最终 Markdown。
    - 调用 `AiNewsRepository.save_latest` 写入 `ai_news.json`。
    - 清空 `entries.json`。

### 5. 基线测试计划

- 使用当前仓库已有的单元测试套件作为基线：
  - `tests/test_data_integrity.py`
  - `tests/test_concurrency_integrity.py`
  - `tests/test_ai_news_api.py`
  - `tests/test_core_helpers.py`
- 参考 `README.md` 与 `TESTING_GUIDE.md` 中推荐命令执行完整 UT 集：
  - 记录测试命令、用例总数、执行时间与结果。
- 后续每个阶段完成后，都必须在此基线之上重新运行整个测试集合，确保无回归。

#### 本次基线记录（2026-02-27）

- 命令：
  - `uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository`
- 结果：
  - 用例数：41
  - 用时：0.989s
  - 结论：全部通过

