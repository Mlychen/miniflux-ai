# Miniflux AI 测试架构与 CI/CD 实施规范 (v1.0)

## 1. 核心目标
建立一套自动化、全覆盖的测试体系，确保 miniflux-ai 在处理 Webhook、LLM 调用、任务调度等复杂场景下的稳定性，并通过 CI/CD 流水线保障发布质量。

特别关注：**资源占用（空转 CPU 保护）**、**外部服务隔离（Mock）**、**并发数据一致性**。

## 2. 技术栈规范
| 类别 | 工具 | 说明 |
| :--- | :--- | :--- |
| **测试框架** | `pytest` | 替代 `unittest`，利用其强大的 Fixture 和 Parameterize 功能 |
| **Mock 工具** | `pytest-mock` | 用于隔离 Miniflux API 和 LLM API |
| **覆盖率** | `pytest-cov` | 目标覆盖率：核心逻辑 > 90% |
| **并发测试** | `pytest-xdist` (可选) | 用于加速测试执行 |
| **资源监控** | `psutil` | **新增**：用于检测空转时的 CPU/内存占用 |
| **CI/CD** | GitHub Actions | 自动化测试与 Docker 构建 |

## 3. 测试分层策略

### 3.1 单元测试 (Unit Test)
**目标**: 验证函数级逻辑，Mock 所有外部 IO。
**位置**: `tests/unit/`

*   **核心模块 (`core/`)**:
    *   `entry_filter.py`: 验证白名单/黑名单逻辑，覆盖边界条件（空列表、None、正则匹配）。
    *   `entry_rendering.py`: 验证 Markdown/HTML 转换，确保格式正确且无注入风险。
    *   `process_entries.py`: 验证去重逻辑 (`InMemoryProcessedNewsIds`)。
*   **适配层 (`adapters/`)**:
    *   `miniflux_gateway.py`: 模拟 404/500/Timeout，验证异常是否被正确封装为内部 Error。
    *   `llm_gateway.py`: 模拟 LLM 返回结构（正常/缺字段/JSON 错误），验证解析鲁棒性。

### 3.2 集成测试 (Integration Test)
**目标**: 验证模块间协作，使用 **临时文件 SQLite** 模拟真实数据库环境。
**位置**: `tests/integration/`
**关键策略**: 使用 `tempfile` 创建独立的 `.db` 文件，确保文件锁行为与生产一致，且测试间数据隔离。

*   **场景 1: Webhook 任务持久化**
    *   模拟 Flask `POST /webhook` -> 验证 SQLite `tasks` 表新增记录 -> 状态为 `pending` -> Payload 完整。
*   **场景 2: 任务处理工作流 (Happy Path)**
    *   初始化 Worker -> 模拟领取任务 -> Mock LLM 返回成功 -> 验证任务状态 `done` -> 验证 `result` 字段写入。
*   **场景 3: 错误处理与重试 (Retry Flow)**
    *   模拟 LLM 抛出临时异常 -> 验证任务状态 `retryable` -> `attempts` +1 -> `next_run_at` 指数退避。
    *   模拟 LLM 抛出致命异常 -> 验证任务状态 `failed` -> 不再重试。

### 3.3 稳定性与性能测试 (Stability & Performance)
**目标**: 验证系统在极端或长期运行下的表现。
**位置**: `tests/performance/`

*   **关键特性：空转资源占用分析 (Idle Resource Usage)**
    *   **方法**: 启动 `TaskWorker` 线程，模拟任务始终为空。
    *   **验证 1 (逻辑层)**: Mock `wait_for_new_task`，断言 timeout 呈 1.5 倍递增的退避趋势。
    *   **验证 2 (物理层)**: 使用 `psutil` 监控测试进程，持续运行 2 秒。
        *   **断言**: 平均 CPU 使用率 < 20% (单核)。
        *   **断言**: 内存无持续增长。
*   **高并发写入 (Concurrency)**
    *   使用 `ThreadPoolExecutor` 模拟 50+ 并发 Webhook 请求。
    *   验证 SQLite 是否出现 `database is locked` 错误（应由重试机制处理）。
    *   验证最终入库记录数 == 请求数（无丢数据）。

## 4. CI/CD 流水线设计

### 4.1 测试流水线 (`.github/workflows/tests.yml`)
*   **触发条件**: `push` (所有分支), `pull_request` (main)。
*   **环境矩阵**: Python 3.10, 3.11, 3.12。
*   **步骤**:
    1.  Checkout 代码。
    2.  安装依赖: `pip install -r requirements.txt -r requirements-dev.txt`。
    3.  **静态检查**: `ruff check .` (确保代码风格)。
    4.  **类型检查**: `mypy --ignore-missing-imports .`。
    5.  **运行测试**:
        ```bash
        pytest --cov=core --cov=adapters --cov=myapp tests/
        ```
    6.  (可选) 上传 Coverage 报告到 Codecov。

### 4.2 构建流水线 (`.github/workflows/docker-image.yml`)
*   **依赖**: 增加 `needs: [tests]`，确保测试通过才构建。
*   **优化**: 使用 `ghcr.io` 缓存层加速构建。

## 5. 实施路线图 (Roadmap)

1.  **基础设施搭建 (Day 1)**
    *   建立 `tests/conftest.py`，定义通用 Fixtures。
    *   配置 `pytest.ini` 并设置 `pythonpath = .`。
2.  **核心单元测试迁移 (Day 1-2)**
    *   迁移 `test_filter.py` 等旧 `unittest` 用例。
    *   补充 `adapters` 的异常处理测试。
3.  **集成测试与空转监控 (Day 2-3)**
    *   实现 SQLite 临时文件 Fixture。
    *   编写 `TaskWorker` 的空转 CPU 监控测试脚本。
4.  **CI 配置与文档 (Day 3)**
    *   编写 GitHub Actions 配置文件。
    *   更新 `README.md` 添加测试运行指南。

## 6. 交付物清单
1.  `tests/` 目录重构代码（包含 `conftest.py` 和分层测试用例）。
2.  `.github/workflows/tests.yml` 配置文件。
3.  更新后的 `.github/workflows/docker-image.yml`。
4.  `docs/TESTING_GUIDE.md`: 包含本地运行测试和查看资源监控报告的指南。
