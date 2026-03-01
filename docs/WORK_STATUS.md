# 工作状态（截至 2026-03-01）

## 已完成

- 全量迁移 tests/ 到 pytest 风格，移除 unittest 入口与依赖
- 新增 assert_utils 用于承接既有断言风格
- 补齐 process-trace 与 debug 路由集成测试
- 更新测试计划中的 CI 步骤（pytest/ruff/mypy）
- 补齐 webhook_ingest 与 task_query 异常路径测试
- 迁移/整理测试目录层级到 tests/unit 与 tests/integration

## 当前验证命令

- pytest --cov=core --cov=adapters --cov=myapp tests/
- ruff check .
- mypy --ignore-missing-imports .

## 未完成与下次建议

- 提升 myapp 覆盖率：补齐更多主流程异常路径测试
