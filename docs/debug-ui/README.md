# 调试前端（Debug UI）分块实施说明

目标：提供一个独立的调试网页（Debug UI），在浏览器直接访问 `http://IP:PORT/debug/`，并用同一应用下的相对路径请求 `miniflux-ai` HTTP API（`/miniflux-ai/*`），用于调试处理链路、失败池、请求池指标等。

本方案重点解决：
- 不依赖 Miniflux 的 Custom JS/DOM 注入
- 浏览器不跨域（同一个 origin：协议 + 域名 + 端口）
- 适配局域网访问（带基础安全措施，避免误暴露）

## 目录

- [00-overview.md](./00-overview.md)：总体架构、部署方式、分块拆分与并行策略
- [10-ui.md](./10-ui.md)：调试页面功能清单、交互与数据结构
- [30-backend.md](./30-backend.md)：后端接口现状与建议增强点
- [40-security-lan.md](./40-security-lan.md)：局域网访问的安全建议（监听地址/防火墙/外部反代）

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

## 当前部署方式

- Debug UI 由应用自身在 `debug.enabled: true` 时提供，不需要仓库内额外的 Nginx 配置。
- 默认监听地址来自 `debug.host` 和 `debug.port`，默认值分别是 `0.0.0.0` 与 `8081`。
- 浏览器访问 `http://IP:PORT/debug/` 时，页面与 `/miniflux-ai/*` API 天然同源，因此不需要额外配置 CORS。

## 推荐的默认路径

- 调试页面：`/debug/`
- miniflux-ai API：`/miniflux-ai/`

说明：统一路径前缀是为了保证前端始终用相对路径（避免跨域与环境差异）。
