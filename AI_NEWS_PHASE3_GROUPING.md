## 阶段 3：基于标签与订阅元数据的 AI News 输入重构

### 1. 目标

- 在 `generate_daily_news` 中真正落实：
  - url/title（或 canonical id）去重；
  - 按订阅元数据 + AI 标签的组合结果进行分组；
  - 按 `created_at` 排序；
- 为 summary_block 提供结构化、干净的输入，提高 AI News 的可读性与主题集中度。

### 2. 修改范围

- 仅修改 `core/generate_daily_news.py` 及其直接使用的辅助函数。
- 不改变 LLM 调用次数（仍为 greeting / summary_block / summary 三段）。
- AI News 输出仍通过 `AiNewsRepository` 以字符串形式写入 `ai_news.json`。

### 3. 数据结构定义

#### 3.1 输入 records（来自 entries.json）

- 阶段 2 后，`entries.json` 中单条记录结构为：

  ```json
  {
    "id": "sha1(url+title)",
    "datetime": "2026-02-25T00:00:00Z",
    "category": "feed.category.title",
    "title": "原始标题",
    "content": "初级摘要",
    "url": "https://example.com/x",

    "ai_category": "科技",
    "ai_subject": "OpenAI",
    "ai_subject_type": "公司",
    "ai_region": "美国",
    "ai_event_type": "产品与发布",
    "ai_group_hint": "科技 / OpenAI / 美国",
    "ai_confidence": 0.9
  }
  ```

#### 3.2 派生标签结构

- 在 `generate_daily_news` 内部，为每条记录派生：

  ```python
  final_tags = {
      "final_category": str,   # 订阅配置映射 > category > ai_category > "其他"
      "final_subject": str,    # 订阅配置映射 > ai_subject > ""
      "final_region": str,     # 订阅配置映射 > ai_region > ""
      "final_event_type": str  # 主要来自 ai_event_type
  }
  ```

- 分组键 `group_key`，通过一个选择函数生成：

  优先级建议：
  1. `final_category` + `final_subject`
  2. `final_category` + `final_region`
  3. `final_category`
  4. `final_subject`
  5. `final_region`
  6. `category`（原订阅分类）
  7. `site`（未来如扩展字段）
  8. 默认 `"其他"`

### 4. 数据流

#### 4.1 读取与防御性去重

1. 通过 `EntriesRepository.read_all()` 读取 entries 列表：
   - `entries = entries_repository.read_all()`
2. 防御性去重：
   - 优先使用 `id` 字段：
     - 建一个 `seen_ids: set[str]`；
     - 过滤出 `unique_entries`。
   - 若历史数据暂未有 `id`，可退化为 `(url, title)` 去重。

#### 4.2 标签合并与分组键生成

对 `unique_entries` 逐条执行：

1. 订阅侧信息：
   - `category = entry["category"]`
   - 未来可追加：site/domain、config 中针对特定 feed 的预设标签。

2. AI 标签：
   - `ai_category = entry.get("ai_category")`
   - `ai_subject = entry.get("ai_subject")`
   - `ai_region = entry.get("ai_region")`
   - `ai_event_type = entry.get("ai_event_type")`

3. 生成 `final_tags`：
   - `final_category`：
     - 若配置对 feed/站点有显式映射 → 使用；
     - 否则使用 `category`；
     - 若 `category` 为空再用 `ai_category`；
     - 否则 `"其他"`。
   - `final_subject`：
     - 若配置有主体预设 → 使用；
     - 否则使用 `ai_subject` 或空字符串。
   - `final_region`：
     - 若配置有区域预设 → 使用；
     - 否则使用 `ai_region` 或空字符串。
   - `final_event_type`：
     - 优先使用 `ai_event_type`。

4. 生成 `group_key = choose_group_key(final_tags, entry)`：
   - 按 3.2 中的优先级规则生成可读分组名。

5. 将条目放入分组：

   ```python
   grouped: dict[str, list[entry_with_tags]] = defaultdict(list)
   grouped[group_key].append({**entry, **final_tags})
   ```

#### 4.3 组内排序

- 对于每个 `group_key` 对应的列表：
  - 按 `datetime` 降序排序（最近的新闻排最前）。
  - 若 datetime 相同，可按 title 或 id 做次序保证。

#### 4.4 生成 summary_block 输入文本

- 遍历分组并构造结构化文本，例如：

  ```text
  【{group_key}】
  - {title1}
    {summary1}

  - {title2}
    {summary2}
  ```

- 拼接所有分组文本为一个大的 `contents_for_summary_block`，作为 summary_block prompt 的输入。
- 如有需要，可适度调整 config 中 summary_block 的 prompt 文案，说明输入已经按主题分组。

### 5. 测试计划

#### 5.1 分组键与标签合并单元测试

- 新增：`tests/test_ai_news_grouping.py`
- 用例示例：
  - 无 AI 标签，仅有订阅 category：
    - 确认 group_key 使用 category。
  - 有 AI category/subject/region：
    - 确认 group_key 优先使用 `final_category / final_subject`。
  - 订阅与 AI 标签冲突：
    - 确认按照“订阅优先，AI 补充”的规则生成 final_tags。

#### 5.2 组内排序测试

- 在同一 group 中构造多条不同 datetime 的记录：
  - 断言排序结果为时间降序。

#### 5.3 summary_block 输入结构测试

- 扩展 `tests/test_data_integrity.py`：
  - 使用 Dummy LLM gateway 记录 summary_block 调用的输入文本；
  - 构造多个 group、多个条目的场景；
  - 断言：
    - 文本中包含预期的分组标题（例如以 `【` 或 `####` 引导）；
    - 每个条目的 title 和 content（摘要）均出现在对应分组下；
    - 条目顺序与分组 + 时间排序一致。

#### 5.4 回归测试

- 执行阶段 2 及之前的完整测试集合，确保：
  - 数据完整性用例全部通过；
  - AI News API 行为仍然稳定；
  - 并发相关用例无回归。

