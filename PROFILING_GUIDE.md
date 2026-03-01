# 本地 Profiling 指南（不依赖外部服务）

目标：只分析本地 CPU / 内存资源消耗（不包含远程 LLM、Miniflux 等外部服务带来的网络等待）。

## 1) 快速开始：对单测做 CPU profiling（cProfile）

推荐先从“有代表性的单测模块”入手，避免需要真实 Miniflux/LLM 环境。

### 1.1 生成 .pstats

- Webhook/API 路径（包含 Flask test client + webhook/task worker 相关代码）：
  - `uv run python -m cProfile -o runtime/profile_webhook_api.pstats -m unittest -q tests.test_webhook_api`
- 批处理路径（并发调度与异常聚合）：
  - `uv run python -m cProfile -o runtime/profile_batch_usecase.pstats -m unittest -q tests.test_batch_usecase`
- 数据一致性/存储路径（JSON/SQLite 仓库读写）：
  - `uv run python -m cProfile -o runtime/profile_data_integrity.pstats -m unittest -q tests.test_data_integrity`

### 1.2 查看 Top 热点（按累计耗时 cumtime）

- `uv run python -c "import pstats; p=pstats.Stats('runtime/profile_webhook_api.pstats'); p.strip_dirs().sort_stats('cumtime').print_stats(60)"`

常用筛选：

- 只看某个关键函数/模块：
  - `uv run python -c "import pstats; p=pstats.Stats('runtime/profile_webhook_api.pstats'); p.strip_dirs().sort_stats('cumtime').print_stats('process_entries', 60)"`
  - `uv run python -c \"import pstats; p=pstats.Stats('runtime/profile_webhook_api.pstats'); p.strip_dirs().sort_stats('cumtime').print_stats('json_storage', 60)\"`

## 2) 更贴近真实负载：使用内置 profiling harness（无外部依赖）

仓库提供了一个本地负载生成器，用于复现：

- 批处理并发调度 + 逐条处理（包含 markdown 渲染、字符串拼接、JSON 解析等本地 CPU 开销）
- AI News 生成链路（全量读入、去重、分组、排序、大字符串拼接等）

脚本位置：

- [profile_local.py](file:///d:/Code/miniflux-ai/tools/profile_local.py)

### 2.1 批处理链路（CPU）

- 先用单线程看“纯 CPU 热点”（避免线程等待/调度噪音）：
  - `uv run python tools/profile_local.py --scenario batch --entries 500 --content-bytes 4000 --max-workers 1 --profile-out runtime/profile_batch_load.pstats --top 80`
- 再用多线程观察“并发调度/锁竞争”：
  - `uv run python tools/profile_local.py --scenario batch --entries 500 --content-bytes 4000 --max-workers 4 --profile-out runtime/profile_batch_concurrency.pstats --top 80`

输出包含：

- summary：本次运行处理条目数、写入文件大小等
- elapsed_ms：总耗时
- pstats：Top 热点函数列表
- pstats saved：pstats 文件路径（如果指定了 --profile-out）

### 2.2 AI News 链路（CPU）

- `uv run python tools/profile_local.py --scenario ai-news --entries 2000 --content-bytes 800 --profile-out runtime/profile_ai_news.pstats --top 80`

### 2.3 内存分配差异（tracemalloc）

对同一 workload 额外打开 tracemalloc，对比“运行前 vs 运行后”的分配差异（按 lineno 聚合）：

- `uv run python tools/profile_local.py --scenario batch --entries 500 --content-bytes 4000 --tracemalloc --tracemalloc-top 30 --top 40`

输出中的 `[tracemalloc top]` 会列出增长最多的分配点（文件:行号 + 分配大小）。

## 3) 建议的分析顺序（只看本地 CPU/内存）

1. 先跑单测 cProfile，锁定 Top 函数（减少噪音）
2. 再跑 harness 的 batch/ai-news，放大数据量复现趋势
3. 对“Top 函数”做定点验证：
   - JSON/SQLite：观察读写次数、每次写入字节数、是否全量 dump
   - 字符串/markdown：观察 render 与拼接是否占比过高
   - 队列线程：观察空闲时是否存在自旋（忙等）

## 4) 常见热点的解读模板

- `common/task_store_sqlite.py` / `common/sqlite_manager.py` 高占比：优先检查任务 claim/update 查询与索引是否匹配。
- `markdown.py` 高占比：说明渲染开销高，agent 多/文本长时会放大。
- `re.py` / `_parse_preprocess_output` 高占比：说明正则回退路径在处理异常文本。
- `core/task_worker.py` 高占比且吞吐低：优先检查 worker 参数（batch/lease/poll）和重试抖动。

## 5) Windows 提示

- 建议先创建输出目录：
  - `mkdir runtime`
- `.pstats` 可以直接用 pstats 查看；如需可视化（可选），再引入本地工具（不需要任何外部服务）。
