# 00. 总体方案与分块并行

## 背景与目标

你的真实需求是调试 `miniflux-ai`（接口可用性、请求池状态、失败条目、手动触发处理等），并希望不受 Miniflux Web UI 结构、Custom JS 注入、同域路由限制影响。

目标是做一个独立 Debug UI：
- 通过浏览器直接访问：`http://IP:PORT/debug/`
- Debug UI 内部通过同源请求调用：`/miniflux-ai/*`

## 关键约束

- 浏览器同源规则：页面 origin 与 API origin 需要一致，才能避免 CORS。
- 局域网可访问：入口需要监听 `0.0.0.0`，并通过安全措施限制访问范围（见 [40-security-lan.md](./40-security-lan.md)）。

## 总体架构（推荐）

使用一个入口（Nginx/反代）统一对外暴露 `IP:PORT`，通过路径分发：
- `/debug/` -> Debug UI 静态文件
- `/miniflux-ai/` -> 反代到 `miniflux-ai`（Flask）
- （可选）`/` -> Miniflux

这样 Debug UI 页面里永远用相对路径：
- `fetch("/miniflux-ai/...")`

## 分块拆分（可并行）

### Block A：Debug UI（前端）

交付物：
- `debug-ui/index.html`（或 `docs/debug-ui` 下先出原型，再迁移到 `debug-ui/`）

内容：
- entry_id 输入 + 触发处理按钮
- failed-entries 表格 + reset 按钮
- metrics 面板
- clear/reset 操作区
- 请求与响应展示区（URL、状态码、耗时、原始 JSON）

可独立并行：只需知道接口路径与返回结构（见 [10-ui.md](./10-ui.md)、[30-backend.md](./30-backend.md)）。

### Block B：同源入口（Nginx/部署）

交付物：
- Nginx 配置：支持 `/debug/` 静态托管与 `/miniflux-ai/` 反代
- Docker Compose 覆盖文件（推荐），或裸机部署指引

可独立并行：不依赖 UI 细节，仅依赖路径约定（见 [20-ingress-nginx.md](./20-ingress-nginx.md)）。

### Block C：后端接口（miniflux-ai）

交付物：
- 确保以下接口稳定：
  - `POST /miniflux-ai/manual-process`
  - `GET /miniflux-ai/user/llm-pool/metrics`
  - `GET /miniflux-ai/user/llm-pool/failed-entries`
  - `POST /miniflux-ai/user/llm-pool/clear`

可选增强：
- 增加 debug 日志/trace_id
- 返回更清晰的错误信息
- 增加“最近处理记录”接口（便于页面展示）

### Block D：局域网安全

交付物：
- Nginx 白名单（CIDR allowlist）
- Basic Auth 或 Debug Token（二选一或同时启用）

注意：安全可以在 Nginx 入口层实现，不必修改 `miniflux-ai`。

## 推荐实施顺序（减少返工）

1. Block B：先把同源入口跑通（/miniflux-ai/ 可达），解决 404/跨域根因
2. Block A：实现 Debug UI MVP（三个 GET + 一个 POST）
3. Block D：补齐局域网访问安全
4. Block C：按调试需求逐步增强后端接口与日志
