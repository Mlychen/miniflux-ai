## 阶段 2：初级加工——单条摘要 + 结构化标签写回 entries.json

### 1. 目标

- 将“单条 entry 的初级加工”标准化为：
  - 面向用户阅读的精炼摘要；
  - 面向后续聚合的结构化标签。
- 初级加工只基于 `title + 正文/长摘要`，不暴露订阅源元数据给 LLM。
- 将初级加工结果写入 `entries.json`，作为 AI News 的干净输入。

### 2. 修改范围

- 扩展 `entries.json` 单条记录的 schema。
- 在处理单条 Miniflux entry 的链路中，引入一个“摘要 + 标签” LLM 调用。
- 不改变 AI News 生成阶段的 LLM 调用结构（本阶段 summary_block 仍只消费 `content`）。

### 3. 数据结构定义

#### 3.1 entries.json 单条记录（扩展版）

- 在阶段 1 的基础上，为每条 summary 记录增加 id 与标签字段：

  ```json
  {
    "id": "sha1(url+title)",                  // canonical id（新字段）
    "datetime": "2026-02-25T00:00:00Z",       // entry.created_at
    "category": "feed.category.title",        // Miniflux 源分类名称
    "title": "原始标题",
    "content": "初级加工得到的摘要文本",
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

#### 3.2 初级加工 LLM 输出 JSON

- 对于单条新闻，LLM 返回一个 JSON 对象：

  ```json
  {
    "summary": "精简摘要……",
    "ai_category": "科技",
    "subject": "OpenAI",
    "subject_type": "公司",
    "region": "美国",
    "event_type": "产品与发布",
    "group_hint": "科技 / OpenAI / 美国",
    "confidence": 0.9
  }
  ```

- 映射规则：
  - `content = summary`
  - `ai_category = ai_category`
  - `ai_subject = subject`
  - 其余字段按名称对应填入。

### 4. 数据流

#### 4.1 单条 entry 初级加工流水线

在阶段 1“入口去重”之后，对每条未见过的 Miniflux entry 实施初级加工：

1. 输入准备：
   - 从原 entry 中取：
     - `title = entry["title"]`
     - `body`：
       - 推荐直接使用 Miniflux 的全文或主摘要内容（当前实现中已有可用字段）。
2. LLM 调用（使用新的初级加工 prompt）：
   - 输入：`title` + `body`。
   - 输出：包含 `summary` 与各个 ai_* 字段的 JSON。
3. 构造 summary entry：
   - 通过现有 `build_summary_entry(entry, summary)` 填充：
     - `datetime`、`category`、`title`、`content`、`url`。
   - 扩展字段：
     - `id`：使用阶段 1 中的 canonical id。
     - `ai_category` / `ai_subject` / `ai_subject_type` / `ai_region` / `ai_event_type` / `ai_group_hint` / `ai_confidence`。
4. 持久化：
   - 使用 `EntriesRepository.append_summary_item(item)` 将记录写入 `entries.json`。

#### 4.2 下游 AI News

- 本阶段不修改 `generate_daily_news` 的 LLM 调用结构：
  - summary_block 仍以 `'\n'.join(entry["content"])` 的形式获得输入。
- 新增标签字段暂不在 AI News 中使用，留待阶段 3 做分组/排序改造。

### 5. 测试计划

#### 5.1 初级加工函数单元测试

- 新增一个使用假 LLM gateway 的测试模块，例如：
  - `tests/test_news_preprocessing.py`。
- 用例设计：
  - 构造一个最简 Miniflux entry（含 title、created_at、feed.category.title、url、content）。
  - 假 LLM gateway 对任意输入返回固定 JSON：
    - `summary = "hello-summary"`
    - 标签字段各自固定值。
  - 通过一个高层函数或 `process_entry` 的路径触发初级加工：
    - 使用 Dummy EntriesRepository 记录传入的 item。
  - 断言：
    - item 中 `content == "hello-summary"`。
    - `id` 为预期 canonical id。
    - `ai_*` 字段与假 LLM 返回值一致。

#### 5.2 entries_repository 兼容性测试

- 扩展 `tests/test_entries_repository.py`：
  - 写入包含新字段的对象；
  - 通过 `read_all()` 读取并验证：
    - 列表长度正确；
    - 每条记录包含所有字段；
    - `clear_all()` 后文件内容为空列表。

#### 5.3 回归测试

- 运行阶段 0 的完整测试集合，确保：
  - 数据完整性测试仍然通过；
  - AI News API 行为无回归；
  - 并发相关测试保持通过。

