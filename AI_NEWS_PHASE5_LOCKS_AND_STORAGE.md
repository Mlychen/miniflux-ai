## 阶段 5：锁拆分与持久化演进（可选）

### 1. 目标

- 拆分 `entries.json` 与 `ai_news.json` 的锁，降低高并发 webhook 写入与 AI News 读取/清理之间的互斥阻塞。
- 为后续从 JSON 文件迁移到轻量级数据库（如 SQLite）预留扩展点，但不强制立即迁移。

### 2. 修改范围

- `myapp/__init__.py` 中应用工厂对 repository 锁的创建与注入逻辑。
- 若选择引入 SQLite，则在 repository 层增加可选实现，并通过配置切换。

### 3. 数据结构定义

#### 3.1 JSON 路线（默认）

- `entries.json` 与 `ai_news.json` 的内容结构保持不变。
- 不再强制共享同一把 `threading.Lock()`，而是各自拥有独立锁实例。

#### 3.2 SQLite 路线（可选）

- `entries` 表（示意）：

  ```sql
  CREATE TABLE entries (
      id TEXT PRIMARY KEY,
      datetime TEXT,
      category TEXT,
      title TEXT,
      content TEXT,
      url TEXT,
      ai_category TEXT,
      ai_subject TEXT,
      ai_subject_type TEXT,
      ai_region TEXT,
      ai_event_type TEXT,
      ai_group_hint TEXT,
      ai_confidence REAL
  );
  ```

- `ai_news` 表（示意）：

  ```sql
  CREATE TABLE ai_news (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT,
      content TEXT
  );
  ```

- 具体 schema 可根据实际需要微调，只要保持与现有 JSON 结构语义一致。

### 4. 数据流

#### 4.1 锁拆分（JSON 路线）

现状（简化）：

- `create_app` 内部大致逻辑：
  - 创建一个 `shared_lock = threading.Lock()`。
  - `EntriesRepository` 与 `AiNewsRepository` 都使用这把 lock。

改造后：

1. 支持外部注入带锁的 repository：
   - 若调用方通过参数传入 `entries_repository` 或 `ai_news_repository`，并且这些对象自带 `lock` 属性：
     - 直接沿用注入对象和其内部锁。
2. 默认构造路径：
   - 未注入自定义 repository 时：
     - 创建两个独立锁：

       ```python
       entries_lock = threading.Lock()
       ai_news_lock = threading.Lock()
       ```

     - 分别用于：
       - `EntriesRepository(path="entries.json", lock=entries_lock)`
       - `AiNewsRepository(path="ai_news.json", lock=ai_news_lock)`

3. json_storage 模块中读写函数继续使用各自 repository 提供的 lock，无需额外改动。

效果：

- webhook 写 `entries.json` 时，仅占用 entries_lock；
- AI News 读/清理 `entries.json` 与读/写 `ai_news.json` 时各自使用对应锁，减少互相阻塞。

#### 4.2 SQLite 路线（可选）

在保留 JSON 实现的基础上，为 repository 层增加 SQLite 版本，实现接口兼容：

1. `EntriesRepositorySQLite`：
   - `append_summary_item(item)`：
     - 映射为 `INSERT OR REPLACE INTO entries (...) VALUES (...)`。
   - `read_all()`：
     - 映射为 `SELECT * FROM entries ORDER BY datetime`。
   - `clear_all()`：
     - 映射为 `DELETE FROM entries`。

2. `AiNewsRepositorySQLite`：
   - `save_latest(content)`：
     - 可以选择仅保留最新一条：
       - 先 `DELETE FROM ai_news` 再插入；
     - 或保留历史，使用 `INSERT` 并在 `consume_latest` 时选择最新记录。
   - `consume_latest()`：
     - 读取最新一条记录；
     - 之后将其内容清空或删除记录，语义与当前 JSON 版一致。

3. 配置开关：
   - 在 `Config` 中增加设置，例如：

     ```yaml
     storage:
       backend: "json"  # 或 "sqlite"
       sqlite_path: "runtime/miniflux_ai.db"
     ```

   - 在应用初始化时，根据配置选择构造 JSON 版或 SQLite 版 repository 实例。

### 5. 测试计划

#### 5.1 锁拆分行为测试

- 扩展 `tests/test_service_containers.py`：
  - 默认构造 app：
    - 断言：
      - `services.entries_repository.lock is not services.ai_news_repository.lock`。
  - 注入自定义 repository：
    - 构造带自定义 lock 的 `EntriesRepository` 与 `AiNewsRepository`；
    - 调用 `create_app`；
    - 断言：
      - app 上下文中 `services.entries_repository` 与 `services.ai_news_repository` 分别与注入对象相同；
      - 其 lock 属性保持不变。

- 运行 `tests/test_concurrency_integrity.py`：
  - 确认拆分锁后并发行为无回归。

#### 5.2 SQLite repository 行为测试（如实施）

- 新增：
  - `tests/test_entries_repository_sqlite.py`
  - `tests/test_ai_news_repository_sqlite.py`

- 用例示例：
  - entries repository：
    - 写入多条记录；
    - 通过 `read_all()` 读取，验证字段完整与排序正确；
    - 调用 `clear_all()` 后，再读取为空列表。
  - ai_news repository：
    - 调用 `save_latest()` 写多次；
    - 调用 `consume_latest()`：
      - 断言返回内容为最后一次保存的值；
      - 断言再次调用返回空字符串。

- 一致性测试：
  - 使用相同的逻辑驱动 JSON 版与 SQLite 版 repository；
  - 断言两种 backend 下，`read_all()` 的结果语义一致。

#### 5.3 回归测试

- 每次对锁或存储 backend 做变更后，执行阶段 4 及之前的完整测试集合：
  - 保证 AI News 行为不变；
  - 保证 webhook 与轮询模式下的并发行为稳定；
  - 保证日志中用于观测 AI News 生成与错误的关键字段仍然可用。

