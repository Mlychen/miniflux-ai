# 工作状态（截至 2026-03-01）

## 已完成

- 全量迁移 tests/ 到 pytest 风格，移除 unittest 入口与依赖
- 新增 assert_utils 用于承接既有断言风格
- 补齐 process-trace 与 debug 路由集成测试
- 更新测试计划中的 CI 步骤（pytest/ruff/mypy）
- 补齐 webhook_ingest 与 task_query 异常路径测试
- 迁移/整理测试目录层级到 tests/unit 与 tests/integration
- 修复 `<blockquote>` 起始正文被误判为已处理而跳过 LLM 的问题
- 新增 `summary_archive` 持久化摘要归档层
- 新增 `Webhook -> TaskWorker -> AI News -> RSS` 自动化 E2E 测试

## 当前验证命令

- pytest --cov=core --cov=adapters --cov=myapp tests/
- ruff check .
- mypy --ignore-missing-imports .
- uv run pytest tests/integration/test_e2e_webhook_ai_news_flow.py

## 未完成与下次建议

- 提升 myapp 覆盖率：补齐更多主流程异常路径测试
