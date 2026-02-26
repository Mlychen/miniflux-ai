## 阶段 4：LLM 重试与降级策略

### 1. 目标

- 为 AI News 的三段 LLM 调用（greeting / summary_block / summary）增加有限重试机制。
- 定义降级路径，保证即使部分 LLM 调用失败，仍能产出“最小可用”的 AI News 内容。
- 维持整体结构与日志可观测性，方便后续排查。

### 2. 修改范围

- 在 usecase 层定义 safe_llm_call 工具函数。
- 修改 `generate_daily_news` 中对 greeting / summary_block / summary 的调用方式。
- 调整 daily news 内容组合逻辑，使其容忍 summary 缺失，并支持 summary_block 降级内容。

### 3. 数据结构定义

- 本阶段不引入新的持久化字段。
- 运行时关注的状态：
  - 每次 LLM 调用的结果文本（可能为 None）。
  - 最后一次异常对象（仅用于日志记录）。

### 4. 数据流

#### 4.1 safe_llm_call 工具函数

- 函数签名（示意）：

  ```python
  def safe_llm_call(prompt, text, logger, llm_client, retries=2, backoff_seconds=1.0):
      ...
  ```

- 行为：
  - 最多尝试 `retries + 1` 次调用 `llm_client.get_result(prompt, text, logger)`。
  - 捕获所有异常，记录 error 级别日志，内容包括尝试次数与异常信息。
  - 每次失败后，可按 `backoff_seconds * (attempt+1)` 做简单线性退避。
  - 若某次调用成功，立即返回 `(result_text, None)`。
  - 若所有尝试均失败，返回 `(None, last_exception)`。

#### 4.2 greeting 调用与降级

1. 调用：

   ```python
   greeting, err_g = safe_llm_call(
       config.ai_news_prompts["greeting"],
       current_datetime_text,
       logger,
       llm_client,
   )
   ```

2. 降级策略：
   - 若 `greeting` 为 None：
     - 使用本地字符串模板构造一个简短 greeting，例如：
       - 根据当前小时选择“早上好/下午好/晚上好”，拼入日期。
     - 记录 warning 日志，标记已进入 greeting 降级路径。

#### 4.3 summary_block 调用与降级

1. 正常调用：

   ```python
   summary_block, err_sb = safe_llm_call(
       config.ai_news_prompts["summary_block"],
       contents_for_summary_block,
       logger,
       llm_client,
   )
   ```

2. 降级策略：
   - 若 `summary_block` 为 None：
     - 构造降级版“标题列表”内容，作为替代的 summary_block：
       - 遍历阶段 3 中已分好组、排序后的 entries：
         - 按 `group_key` 输出分组标题；
         - 每个分组下列出若干条 `日期 + 标题`，可选附带简短摘要前几句。
     - 记录 warning 日志，清晰标注“summary_block 使用标题列表降级输出”。

3. 标记：
   - 可在运行时维护一个布尔标记 `summary_block_degraded`，供后续 summary 阶段决策使用。

#### 4.4 summary 调用与降级

1. 调用前提：
   - 仅当 `summary_block` 非空时尝试生成 summary。
2. 调用：

   ```python
   summary, err_s = safe_llm_call(
       config.ai_news_prompts["summary"],
       summary_block,
       logger,
       llm_client,
   )
   ```

3. 降级策略：
   - 若 `summary` 为 None：
     - 记录 warning 日志，说明 summary 阶段使用降级。
     - 可以选择：
       - 完全省略 summary 段（更简单、更安全）。
       - 或者从 summary_block 文本中抽取前若干“关键信号”行，拼出一个简要 summary。
   - 若 `summary_block_degraded` 为 True（说明 summary_block 已经是“标题列表版”）：
     - 可以直接跳过 summary 调用，仅输出 greeting + News 段。

#### 4.5 内容组合逻辑

- 修改 daily news 最终内容的组合逻辑，使其适配上述情况：

  - 正常路径（有 summary）：
    - 保持现有结构：

      ```text
      greeting

      ### Summary
      summary

      ### News
      summary_block
      ```

  - summary 缺失路径：
    - 仅输出 greeting + News 段：

      ```text
      greeting

      ### News
      summary_block_or_degraded
      ```

- 最终仍由 `compose_daily_news_content` 或其附近逻辑生成完整 Markdown，并通过 `AiNewsRepository.save_latest` 写入。

### 5. 测试计划

#### 5.1 safe_llm_call 单元测试

- 新增：`tests/test_safe_llm_call.py`
- 用例示例：
  - 假 LLM gateway 在前两次调用抛异常，第三次返回 `"ok"`：
    - 断言 safe_llm_call 返回 `"ok"`，error 为 None。
    - 断言 LLM 调用次数为 3。
  - 假 LLM gateway 始终抛异常：
    - 断言 safe_llm_call 返回 `(None, last_exception)`。
    - 可通过 stub logger 验证 error 日志调用次数为 `retries+1`。

#### 5.2 greeting 降级行为测试

- 在数据完整性测试中增加场景：
  - 让 Dummy LLM 在 greeting 阶段始终抛异常；
  - 断言：
    - 生成的 AI News 文本中仍然有 greeting 段（来自本地模板）；
    - 日志中包含降级相关 warning。

#### 5.3 summary_block 降级行为测试

- 场景：
  - Dummy LLM 在 summary_block 阶段始终抛异常；
  - 断言：
    - AI News 文本中包含“标题列表”形式的 News 内容；
    - 不因 summary_block 失败而完全丢失 AI News；
    - entries.json 在 finally 块仍被清理。

#### 5.4 summary 降级行为测试

- 场景：
  - Dummy LLM 在 summary 阶段抛异常，其他阶段成功；
  - 断言：
    - 最终 AI News 文本中没有 Summary 段（或使用简化 summary），但 News 段正常；
    - ai_news.json 写入成功，且 Miniflux feed 刷新流程正常执行。

#### 5.5 回归测试

- 执行阶段 3 及之前的完整测试集合：
  - 确认所有数据完整性、并发、API 测试仍然通过；
  - 日志引导文档（如 LOGGING_FILTER_GUIDE）中提到的关键日志字段仍然存在或有明确替代。

