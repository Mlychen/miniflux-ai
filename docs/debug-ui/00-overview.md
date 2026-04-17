# 00. 总体方案与分块并行

## 背景与目标

你的真实需求是调试 `miniflux-ai`（接口可用性、请求池状态、失败条目、手动触发处理等），并希望不受 Miniflux Web UI 结构、Custom JS 注入、同域路由限制影响。

目标是做一个独立 Debug UI：
- 通过浏览器直接访问：`http://IP:PORT/debug/`
- Debug UI 内部通过同源请求调用：`/miniflux-ai/*`

## 关键约束

- 浏览器同源规则：页面 origin 与 API origin 需要一致，才能避免 CORS。
- 局域网可访问：应用需要监听 `0.0.0.0`，并通过网络层安全措施限制访问范围（见 [40-security-lan.md](./40-security-lan.md)）。

## 总体架构（推荐）

当前仓库的推荐方式是直接使用应用内建的 Debug UI：
- `/debug/` -> 应用直接返回调试页面与静态资源
- `/miniflux-ai/` -> 同一 Flask 应用提供调试与业务 API
- 是否对外暴露由 `debug.host` / `debug.port` 和宿主机网络策略控制

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
- tasks failure-groups 面板（分组查询/任务样本/重入队）
- 请求与响应展示区（URL、状态码、耗时、原始 JSON）

可独立并行：只需知道接口路径与返回结构（见 [10-ui.md](./10-ui.md)、[30-backend.md](./30-backend.md)）。

### Block B：应用部署与访问方式

交付物：
- `debug.enabled: true` 的配置说明
- `debug.host` / `debug.port` 的监听说明
- 裸机或容器环境下的访问指引

可独立并行：不依赖 UI 细节，仅依赖路径约定和当前应用内建路由。

### Block C：后端接口（miniflux-ai）

交付物：
- 确保以下接口稳定：
- `POST /miniflux-ai/manual-process`
- `GET /miniflux-ai/user/llm-pool/metrics`
- `GET /miniflux-ai/user/llm-pool/failed-entries`
- `POST /miniflux-ai/user/llm-pool/clear`
- `GET /miniflux-ai/user/tasks/<task_id>`
- `GET /miniflux-ai/user/tasks/failure-groups`
- `GET /miniflux-ai/user/tasks/failure-groups/tasks`
- `POST /miniflux-ai/user/tasks/failure-groups/requeue`
- `POST /miniflux-ai/user/tasks/<task_id>/requeue`

可选增强：
- 增加 debug 日志/trace_id
- 返回更清晰的错误信息
- 增加“最近处理记录”接口（便于页面展示）

### Block D：局域网安全

交付物：
- 监听地址约束（例如仅绑定内网 IP）
- 主机/容器层防火墙、VPN、网段限制
- 如有需要，外部反代层的附加鉴权方案

注意：仓库不再维护 Nginx 示例配置；如果你需要外部反代，可自行放在应用前面。

## 推荐实施顺序（减少返工）

1. Block B：先把应用监听与访问地址跑通（`/debug/` 与 `/miniflux-ai/` 可达）
2. Block A：实现 Debug UI MVP（三个 GET + 一个 POST）
   - 追加任务排障 MVP（失败分组 + 重入队）
3. Block D：补齐局域网访问安全
4. Block C：按调试需求逐步增强后端接口与日志
