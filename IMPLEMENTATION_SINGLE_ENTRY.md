#VN|# 单入口 + webhook 缓冲 + 去重 实施文档
#KM|
#KH|## 目标
#RW|
#KK|- 仅启用一个入口（webhook 或轮询），避免并发导致重复处理与重复 LLM 调用。
#VT|- 为 webhook 增加最小改动的缓冲与后台消费，避免请求阻塞或超时。
#ZX|- 增强幂等与去重策略，降低重复处理概率与算力浪费。
#XW|
#VY|## 非目标
#SK|
#SB|- 不引入外部队列（Redis/RabbitMQ）；仅预留接口。
#VQ|- 不改变现有 LLM 处理逻辑与输出格式。
#QM|
#RH|## 实施状态
#ZR|
- ✅ 1) 配置新增：entry_mode, webhook_queue_max_size, webhook_queue_workers, dedup_marker
- ✅ 2) 单入口切换：resolve_entry_mode, should_start_flask, should_start_polling
- ✅ 3) 队列模块：core/queue.py (QueueBackend, InMemoryQueueBackend, WebhookQueue)
- ✅ 4) 去重逻辑：ProcessedEntriesRepository + process_entries.py 去重检查
- ✅ 5) 队列集成：myapp/__init__.py, myapp/ai_summary.py, main.py

### 待完成（方案A）

- ✅ 3.1) myapp/__init__.py：集成队列初始化（Flask app.config 方式）
- ✅ 3.2) myapp/ai_summary.py：使用队列异步处理
- ✅ 3.3) main.py：启动后台消费者线程
#MW|
#YQ|- ✅ 1) 配置新增：entry_mode, webhook_queue_max_size, webhook_queue_workers, dedup_marker
#YJ|- ✅ 2) 单入口切换：resolve_entry_mode, should_start_flask, should_start_polling
#YJ|- ✅ 3) 队列模块：core/queue.py (QueueBackend, InMemoryQueueBackend, WebhookQueue)
#YW|- ✅ 4) 去重逻辑：ProcessedEntriesRepository + process_entries.py 去重检查
#ZW|
#JK|### 待完成（方案A）
#QV|
#QV|- ⏳ 3.1) myapp/__init__.py：集成队列初始化（Flask app.config 方式）
#QV|- ⏳ 3.2) myapp/ai_summary.py：使用队列异步处理
#QV|- ⏳ 3.3) main.py：启动后台消费者线程
#RV|
#RM|## 方案A：Flask app.config 存储队列
#MW|
#JM|### 设计原则
#QP|
#KM|1. 不修改 AppServices dataclass（保持向后兼容）
#QM|2. 队列存储在 Flask app.config 中（符合 Flask 最佳实践）
#QM|3. 渐进式启用（仅 entry_mode=webhook 时启用）
#QM|4. 测试友好（直接 mock app.config）
#QM|
#QT|### 实现细节
#MV|
#KM|#### 3.1 myapp/__init__.py 集成
#MV|
#QM|位置：[myapp/__init__.py](file:///d:/Code/miniflux-ai/myapp/__init__.py)
#QM|
#QM|```python
#QM|from core.queue import InMemoryQueueBackend, WebhookQueue
#QM|
#QM|def create_app(...):
#QM|    # ... 现有代码 ...
#QM|    
#QM|    # 仅 webhook 模式时创建队列
#QM|    app_webhook_queue = None
#QM|    entry_mode = getattr(config, 'miniflux_entry_mode', 'auto')
#QM|    webhook_secret = getattr(config, 'miniflux_webhook_secret', None)
#QM|    
#QM|    if entry_mode == 'webhook' and webhook_secret:
#QM|        max_size = getattr(config, 'miniflux_webhook_queue_max_size', 1000)
#QM|        workers = getattr(config, 'miniflux_webhook_queue_workers', 2)
#QM|        queue_backend = InMemoryQueueBackend(max_size=max_size)
#QM|        app_webhook_queue = WebhookQueue(backend=queue_backend, workers=workers)
#QM|    
#QM|    # 存储在 Flask app.config（方案A核心）
#QM|    app.config['WEBHOOK_QUEUE'] = app_webhook_queue
#QM|    
#QM|    # ... 现有代码 ...
#QM|```

> ⚠️ **注意事项**：`entry_mode` 判断应使用 `resolve_entry_mode()` 函数而非直接读取配置值。如果用户配置为 `auto`，直接对比字符串会导致队列无法创建。
#QM|
#QT|#### 3.2 myapp/ai_summary.py 异步处理
#QM|
#QM|位置：[myapp/ai_summary.py](file:///d:/Code/miniflux-ai/myapp/ai_summary.py)
#QM|
#QM|```python
#QM|from flask import current_app
#QM|from core.process_entries_batch import process_entries_batch
#QM|
#QM|def register_ai_summary_routes(app):
#QM|    @app.route('/api/miniflux-ai', methods=['POST'])
#QM|    def miniflux_ai():
#QM|        # ... 签名验证 ...
#QM|        
#QM|        # 从 Flask app.config 获取队列（方案A）
#QM|        webhook_queue = current_app.config.get('WEBHOOK_QUEUE')
#QM|        
#QM|        batch_entries = [...]
#QM|        
#QM|        if webhook_queue:
#QM|            # 异步模式：入队并立即返回
#QM|            if webhook_queue.is_full:
#QM|                return jsonify({'status': 'error', 'message': 'queue full'}), 429
#QM|            
#QM|            task = {
#QM|                'config': config,
#QM|                'batch_entries': batch_entries,
#QM|                'miniflux_client': miniflux_client,
#QM|                'entry_processor': entry_processor,
#QM|                'llm_client': llm_client,
#QM|                'logger': logger,
#QM|            }
#QM|            webhook_queue.enqueue(task)
#QM|            return jsonify({'status': 'accepted'}), 202
#QM|        else:
#QM|            # 同步模式：直接处理（polling 模式或无队列配置）
#QM|            result = process_entries_batch(...)
#QM|            if result['failures'] > 0:
#QM|                return jsonify({'status': 'error'}), 500
#QM|            return jsonify({'status': 'ok'})
#QM|```

> ⚠️ **注意事项**：`task` 字典传递的对象引用在多线程环境下可能存在生命周期问题。需确认 `config`、`miniflux_client` 等对象是否线程安全，或考虑传递标识符而非对象引用。
#QM|
#QT|#### 3.3 main.py 启动消费者线程
#QM|
#QM|位置：[main.py](file:///d:/Code/miniflux-ai/main.py) my_flask() 函数
#QM|
#QM|```python
#QM|def my_flask(services):
#QM|    logger = services.logger
#QM|    app = create_app(
#QM|        config=services.config,
#QM|        miniflux_client=services.miniflux_client,
#QM|        llm_client=services.llm_client,
#QM|        logger=services.logger,
#QM|        entry_processor=services.entry_processor,
#QM|        entries_repository=services.entries_repository,
#QM|        ai_news_repository=services.ai_news_repository,
#QM|    )
#QM|    
#QM|    # 启动后台消费者（仅当队列存在时）
#QM|    webhook_queue = app.config.get('WEBHOOK_QUEUE')
#QM|    if webhook_queue:
#QM|        from core.process_entries_batch import process_entries_batch
#QM|        
#QM|        def processor_fn(task):
#QM|            process_entries_batch(
#QM|                task['config'],
#QM|                task['batch_entries'],
#QM|                task['miniflux_client'],
#QM|                task['entry_processor'],
#QM|                task['llm_client'],
#QM|                task['logger'],
#QM|            )
#QM|        
#QM|        webhook_queue.start(processor_fn)
#QM|        logger.info(f"Started webhook queue with {webhook_queue._workers} workers")
#QM|    
#QM|    logger.info('Starting API')
#QM|    app.run(host='0.0.0.0', port=80)
#QM|```

> ⚠️ **注意事项**：Flask 开发环境 `app.run(debug=True)` 会触发进程 fork 导致消费者线程重复启动。生产环境无此问题，开发环境建议添加 `use_reloader=False` 或线程启动保护。
#QM|
#QT|### 测试方法
#MV|
#KM|#### 单元测试
#MV|
#KM|```bash
#KM|# 现有测试（必须全部通过）
#KM|uv run python -m unittest -q tests.test_filter tests.test_config tests.test_data_integrity tests.test_webhook_api tests.test_concurrency_integrity tests.test_ai_news_api tests.test_batch_usecase tests.test_service_containers tests.test_adapters tests.test_core_helpers tests.test_ai_news_repository tests.test_entries_repository
#KM|```
#KM|
#KM|#### 新增队列测试
#KM|
#KM|```python
#KM|# tests/test_webhook_queue.py
#KM|
#KM|import unittest
#KM|from myapp import create_app
#KM|from common.config import Config
#KM|from adapters import LLMGateway, MinifluxGateway
#KM|from common.logger import get_logger
#KM|from core.queue import InMemoryQueueBackend, WebhookQueue
#KM|
#KM|class TestWebhookQueue(unittest.TestCase):
#KM|    def test_queue_stored_in_app_config(self):
#KM|        """验证队列存储在 Flask app.config 中"""
#KM|        config = Config.from_dict({
#KM|            'miniflux': {'entry_mode': 'webhook', 'webhook_secret': 'test'},
#KM|            'llm': {'model': 'test'},
#KM|            'agents': {}
#KM|        })
#KM|        app = create_app(
#KM|            config=config,
#KM|            miniflux_client=MinifluxGateway('http://localhost', 'key'),
#KM|            llm_client=LLMGateway(config),
#KM|            logger=get_logger('INFO'),
#KM|            entry_processor=lambda *a, **k: None,
#KM|        )
#KM|        
#KM|        # 验证队列存在
#KM|        self.assertIn('WEBHOOK_QUEUE', app.config)
#KM|        self.assertIsNotNone(app.config['WEBHOOK_QUEUE'])
#KM|    
#KM|    def test_no_queue_when_polling_mode(self):
#KM|        """验证 polling 模式不创建队列"""
#KM|        config = Config.from_dict({
#KM|            'miniflux': {'entry_mode': 'polling'},
#KM|            'llm': {'model': 'test'},
#KM|            'agents': {}
#KM|        })
#KM|        app = create_app(
#KM|            config=config,
#KM|            miniflux_client=MinifluxGateway('http://localhost', 'key'),
#KM|            llm_client=LLMGateway(config),
#KM|            logger=get_logger('INFO'),
#KM|            entry_processor=lambda *a, **k: None,
#KM|        )
#KM|        
#KM|        # 验证队列为 None
#KM|        self.assertIsNone(app.config.get('WEBHOOK_QUEUE'))
#KM|    
#KM|    def test_webhook_returns_202_when_queued(self):
#KM|        """验证 webhook 返回 202 当使用队列时"""
#KM|        # TODO: 实现完整的端到端测试
#KM|        pass
#KM|    
#KM|    def test_webhook_returns_429_when_queue_full(self):
#KM|        """验证队列满时返回 429"""
#KM|        # TODO: 实现队列满测试
#KM|        pass
#KM|
#KM|if __name__ == '__main__':
#KM|    unittest.main()
#KM|```
#KM|
#KM|#### 回归测试
#KM|
#KM|```bash
#KM|# 每次修改后必须运行
#KM|uv run python -m unittest -q tests.test_webhook_api tests.test_service_containers
#KM|```
#KM|
#KM|#### 手动测试
#KM|
#KM|```bash
#KM|# 1. 启动应用（webhook 模式）
#KM|uv run python main.py
#KM|
#KM|# 2. 模拟 webhook 请求
#KM|# curl -X POST http://localhost/api/miniflux-ai \
#KM|#   -H "Content-Type: application/json" \
#KM|#   -H "X-Miniflux-Signature: <signature>" \
#KM|#   -d '{"entries": [...], "feed": {...}}'
#KM|
#KM|# 3. 验证返回 202（队列模式）或 200（同步模式）
#KM|# 4. 检查日志中是否有 "Started webhook queue" 
#KM|```
#KM|
#QT|### 数据流变化
#MV|
#KM|#### 无队列（当前）
#KM|```
#KM|Miniflux webhook → Flask (阻塞等待) → LLM × N → Miniflux API × N → 返回
#KM|```
#KM|
#KM|#### 有队列（方案A）
#KM|```
#KM|Miniflux webhook → Flask (立即返回202) → 队列 → 后台Worker → LLM × N → Miniflux API × N
#KM|```
#KM|
#QT|### 风险与缓解
#MV|
#KM|1. **队列满导致429**
#KM|   - 缓解：配置合理的 webhook_queue_max_size
#KM|   - 监控：日志记录队列满事件
#KM|
#KM|2. **后台处理失败**
#KM|   - 缓解：worker 内部 try-except 捕获异常，不影响主请求
#KM|   - 监控：记录处理失败日志
#KM|
#KM|3. **进程重启丢失**
#KM|   - 现状：内存队列，进程重启队列清空
#KM|   - 后续：可替换为 Redis 队列（已预留 QueueBackend 接口）
#KM|
#QT|## 现状概要

## 目标

- 仅启用一个入口（webhook 或轮询），避免并发导致重复处理与重复 LLM 调用。
- 为 webhook 增加最小改动的缓冲与后台消费，避免请求阻塞或超时。
- 增强幂等与去重策略，降低重复处理概率与算力浪费。

## 非目标

- 不引入外部队列（Redis/RabbitMQ）；仅预留接口。
- 不改变现有 LLM 处理逻辑与输出格式。

## 现状概要

- 轮询入口：定时调用 [fetch_unread_entries](file:///d:/Code/miniflux-ai/core/fetch_unread_entries.py#L1-L23) 拉取未读条目并批量处理。
- webhook 入口：路由 /api/miniflux-ai 接收 webhook 并批量处理。[ai_summary.py](file:///d:/Code/miniflux-ai/myapp/ai_summary.py#L1-L48)
- 启动逻辑：同时启动轮询与 Flask（满足条件即启）。[main.py](file:///d:/Code/miniflux-ai/main.py#L50-L144)
- 去重：仅依赖内容前缀过滤。[entry_filter.py](file:///d:/Code/miniflux-ai/core/entry_filter.py#L1-L31)

## 方案总览

1) 配置新增入口模式 `miniflux.entry_mode`，值 `webhook | polling | auto`（默认 auto）。  
2) 启动阶段只启用一个入口：  
   - `webhook`：只启动 Flask（含 webhook 路由），不启动轮询。  
   - `polling`：只启动轮询，不启动 webhook 路由。  
   - `auto`：有 webhook_secret 则 webhook；否则 polling。  
3) webhook 增加内存队列缓冲 + 后台消费线程；并抽象队列接口，便于后续替换外部队列。  
4) 去重策略升级：内容标记 + 持久化去重记录双保险。

## 详细实现步骤

### 1) 配置新增与解析

新增配置项（中文与英文样例均需补充）：

- `miniflux.entry_mode`：`auto | webhook | polling`，默认 `auto`  
- `miniflux.webhook_queue_max_size`：队列上限（默认 1000）  
- `miniflux.webhook_queue_workers`：后台消费并发（默认 2）  
- `miniflux.dedup_marker`：内容标记（默认 `<!-- miniflux-ai:processed -->`）

对应解析：

- 在 [Config](file:///d:/Code/miniflux-ai/common/config.py#L1-L40) 增加字段解析与默认值。

### 2) 单入口切换逻辑

修改启动逻辑：

- 在 [main.py](file:///d:/Code/miniflux-ai/main.py#L50-L144) 中新增入口模式判定函数：  
  - `resolve_entry_mode(config)`：根据 entry_mode 与 webhook_secret 判断最终模式。  
  - `should_start_flask(entry_mode, config)`：webhook 模式或有 ai_news_schedule 时启动。  
  - `should_start_polling(entry_mode)`：仅 polling 模式启动。
- 当 `entry_mode=webhook` 且 `webhook_secret` 缺失时，直接报错终止启动。  
- 当 `entry_mode=polling` 且配置了 `webhook_secret` 时输出 warning，提示 webhook 被禁用。

### 3) webhook 缓冲与队列抽象

新增最小队列接口（建议新增模块 `core/queue.py` 或 `myapp/webhook_queue.py`）：

- `QueueBackend` 协议：  
  - `enqueue(item)`  
  - `dequeue(batch_size)`  
  - `size()`  
- 内存实现：`InMemoryQueueBackend`（基于 `queue.Queue` 或 `collections.deque` + `threading.Condition`）

webhook 处理流程改造（[ai_summary.py](file:///d:/Code/miniflux-ai/myapp/ai_summary.py#L1-L48)）：

1) 校验签名通过后，不直接调用 `process_entries_batch`。  
2) 将 payload 里 entries 组装为批次任务入队。  
3) 若队列满，返回 `429` 并记录日志。  
4) 立即返回 `200`（或 `202`）表示已接收。

后台消费线程：

- 在 app 启动时创建后台 worker（线程或 ThreadPoolExecutor）。  
- worker 持续从队列拉取 batch，调用 `process_entries_batch`。  
- worker 并发度由 `webhook_queue_workers` 控制。  

### 4) 幂等与去重

去重策略双层：

1) **内容标记**  
   - 处理完成后，在 `miniflux_client.update_entry` 写回内容中追加 `dedup_marker`。  
   - 在处理前，若 `entry['content']` 已包含该 marker，则直接跳过。

2) **持久化记录**  
   - 增加 `ProcessedEntriesRepository`（可复用 `EntriesRepository` 结构但存储 `entry_id` 列表）。  
   - 在处理前判定 `entry_id` 是否已处理，已处理则跳过。  
   - 处理完成后追加 `entry_id`。  
   - 建议用单独文件 `processed_entries.json`，避免与 ai_news 记录混用。

代码调整点：

- 在 [process_entries.py](file:///d:/Code/miniflux-ai/core/process_entries.py#L1-L61) 增加去重判断入口：  
  - `if dedup_marker in entry['content']` 或 `processed_repo.contains(entry_id)` -> skip  
  - 成功处理后写回 marker，并记录 entry_id  
- 在 [entry_filter.py](file:///d:/Code/miniflux-ai/core/entry_filter.py#L1-L31) 之外增加更明确的去重判定，避免仅依赖前缀过滤。

### 5) 运行指南补充

在 README 配置部分新增说明：

- entry_mode 的语义与默认行为  
- webhook 与 polling 只能二选一  
- 若启用 webhook，建议配置队列参数  
- 若启用 polling，禁用 Miniflux webhook

### 6) 测试补齐

新增或更新测试：

- `tests.test_config`：覆盖 entry_mode 默认与显式设置  
- `tests.test_webhook_api`：entry_mode=polling 时 webhook 403/404  
- `tests.test_concurrency_integrity`：队列消费完整性  
- `tests.test_data_integrity`：dedup marker 与 processed_entries.json 生效

建议回归：

- `uv run python -m unittest -q tests.test_webhook_api tests.test_concurrency_integrity tests.test_data_integrity`

## 变更清单（文件级）

- 配置：  
  - [common/config.py](file:///d:/Code/miniflux-ai/common/config.py#L1-L40)  
  - config.sample.Chinese.yml  
  - config.sample.English.yml  
  - README.md
- 单入口逻辑：  
  - [main.py](file:///d:/Code/miniflux-ai/main.py#L50-L144)
- webhook 缓冲：  
  - [myapp/ai_summary.py](file:///d:/Code/miniflux-ai/myapp/ai_summary.py#L1-L48)  
  - 新增队列模块（文件名待定）
- 去重：  
  - [core/process_entries.py](file:///d:/Code/miniflux-ai/core/process_entries.py#L1-L61)  
  - 新增 processed_entries.json 的 repo（文件名待定）
- 测试：  
  - [tests/test_config.py](file:///d:/Code/miniflux-ai/tests/test_config.py#L1-L27)  
  - [tests/test_webhook_api.py](file:///d:/Code/miniflux-ai/tests/test_webhook_api.py#L1-L194)  
  - [tests/test_concurrency_integrity.py](file:///d:/Code/miniflux-ai/tests/test_concurrency_integrity.py#L1-L144)  
  - [tests/test_data_integrity.py](file:///d:/Code/miniflux-ai/tests/test_data_integrity.py#L1-L202)

## 风险与回退

- 风险：队列满导致 webhook 被拒；可通过调整 max_size 或采用外部队列缓解。  
- 风险：dedup marker 与历史内容冲突；建议使用 HTML 注释标记以减少误判。  
- 回退：将 entry_mode 设为 polling，暂时禁用 webhook 入口。
