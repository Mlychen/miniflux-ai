# 调试前端（Debug UI）分块实施说明

目标：提供一个独立的调试网页（Debug UI），在浏览器直接访问 `http://IP:PORT/debug/`，用同源请求调用 `miniflux-ai` 的 HTTP API（`/miniflux-ai/*`），用于调试处理链路、失败池、请求池指标等。

本方案重点解决：
- 不依赖 Miniflux 的 Custom JS/DOM 注入
- 浏览器不跨域（同一个 origin：协议 + 域名 + 端口）
- 适配局域网访问（带基础安全措施，避免误暴露）

## 目录

- [00-overview.md](./00-overview.md)：总体架构、约束、分块拆分与并行策略
- [20-ingress-nginx.md](./20-ingress-nginx.md)：同源入口（Nginx）与部署方式（裸机/容器）
- [10-ui.md](./10-ui.md)：调试页面功能清单、交互与数据结构
- [30-backend.md](./30-backend.md)：后端接口现状与建议增强点
- [40-security-lan.md](./40-security-lan.md)：局域网访问的安全建议（白名单/BasicAuth/Token）

## 最小可用交付物（MVP）

- `GET /debug/`：静态调试页面（一个 HTML 即可）
- 页面内使用相对路径调用：
  - `POST /miniflux-ai/manual-process`
  - `GET /miniflux-ai/user/llm-pool/metrics`
  - `GET /miniflux-ai/user/llm-pool/failed-entries`
  - `POST /miniflux-ai/user/llm-pool/clear`
  - `GET /miniflux-ai/user/tasks/failure-groups`
  - `GET /miniflux-ai/user/tasks/failure-groups/tasks`
  - `GET /miniflux-ai/user/tasks/<task_id>`
  - `POST /miniflux-ai/user/tasks/failure-groups/requeue`
  - `POST /miniflux-ai/user/tasks/<task_id>/requeue`

## 推荐的默认路径

- 调试页面：`/debug/`
- miniflux-ai API：`/miniflux-ai/`

说明：统一路径前缀是为了保证前端始终用相对路径（避免跨域与环境差异）。
