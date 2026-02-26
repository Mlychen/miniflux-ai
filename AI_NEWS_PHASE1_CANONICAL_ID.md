## 阶段 1：canonical id 与入口去重

### 1. 目标

- 基于 `url + title` 生成稳定的 canonical id。
- 在入口（`process_entry` 之前）按 id 去重，避免对同一新闻重复调用 LLM。
- 保持 AI News 行为不变，仅削减重复处理与 entries.json 膨胀。

### 2. 修改范围

- 新增 canonical id 工具函数（不依赖外部状态）。
- 新增“已处理 id 集合”接口与内存实现。
- 在 `process_entry` 调用链前增加去重逻辑。
- 暂不修改 `entries.json` 结构（本阶段先不持久化 id）。

### 3. 数据结构定义

#### 3.1 canonical id

- 输入：
  - `url: str | None`
  - `title: str | None`
- 规范化规则（建议实现）：
  - url：
    - 去掉首尾空白；
    - 可选：对 scheme/host 部分统一大小写；
    - 去掉末尾 `/`；
    - 可选：去除常见追踪参数（`utm_*` 等，后续可迭代）。
  - title：
    - `strip()` 去掉首尾空白；
    - 将连续空白压缩为单一空格。
- 拼接字符串：

  ```text
  key_str = normalized_url + "\n" + normalized_title
  ```

- 生成 id：
  - `id = sha1(key_str.encode("utf-8")).hexdigest()`

#### 3.2 ProcessedNewsIds 接口

- 抽象：

  ```python
  class ProcessedNewsIds:
      def seen(self, canonical_id: str) -> bool: ...
      def mark(self, canonical_id: str) -> None: ...
  ```

- 第一版实现：
  - 内部持有一个 `set[str]`。
  - 生命周期跟随进程（不强制持久化）。

### 4. 数据流变更

#### 4.1 Miniflux entry 入口

原流程：Miniflux entry → `process_entry` → 各 agent → `EntriesRepository.append_summary_item`

新流程（只在入口前增加去重）：

1. 从 Miniflux entry 提取：
   - `url = entry.get("url")`
   - `title = entry.get("title")`
2. 调用 `canonical_id = make_canonical_id(url, title)`。
3. 调用 `processed_ids.seen(canonical_id)`：
   - 若返回 True：
     - 记录一次 debug 日志：包含 canonical_id、url、title。
     - 直接返回，不调用任何 LLM，不写 entries.json。
   - 若返回 False：
     - `processed_ids.mark(canonical_id)`。
     - 按现有逻辑继续：
       - 依次调用各 agent 的 LLM；
       - 将结果写入 `EntriesRepository.append_summary_item(...)`。

#### 4.2 下游链路

- `generate_daily_news` 及之后的逻辑在本阶段不做修改。
- entries.json 中的结构保持现状。

### 5. 测试计划

#### 5.1 canonical id 函数测试

- 新增：`tests/test_canonical_id.py`
- 用例示例：
  - 相同 url/title → id 完全相同。
  - url 仅大小写/末尾 `/` 差异 → id 相同。
  - url 缺失，仅有 title → id 仍可生成。
  - 完全不同 url/title → id 明显不同。

#### 5.2 ProcessedNewsIds 行为测试

- 新增：`tests/test_processed_ids.py`
- 用例示例：
  - 初始状态：
    - `seen("x")` 返回 False。
  - `mark("x")` 后：
    - 再次调用 `seen("x")` 返回 True。

#### 5.3 入口去重集成测试

- 可以扩展现有的 `tests/test_concurrency_integrity.py` 或新增专门用例：
  - 构造两条内容相同、url/title 相同的 Miniflux entry。
  - 使用 Dummy LLM gateway 和 Dummy EntriesRepository：
    - 记录 agent 调用次数；
    - 记录 `append_summary_item` 调用次数。
  - 断言：
    - LLM 只被调用一次；
    - entries 只写入一次。

- 完成本阶段实现后：
  - 回归执行阶段 0 的完整测试套件，确保无行为回归。

