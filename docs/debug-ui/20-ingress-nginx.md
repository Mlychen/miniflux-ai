# 20. 同源入口（Nginx）与部署

目标：对外只暴露一个 `http://IP:PORT`，并通过路径分发实现同源：
- `/debug/`：Debug UI 静态页面
- `/miniflux-ai/`：反代到 miniflux-ai
- （可选）`/`：反代到 Miniflux

## 方案一：Docker（推荐，和现有 compose 最兼容）

### 组件

- `nginx`：统一入口（对外暴露 80 或 443）
- `miniflux`：原服务（内部 8080）
- `miniflux_ai`：本项目 Flask（内部 80）
- `postgres`：Miniflux DB

### 路由策略（示例）

在 Nginx 配置中：
- `location /miniflux-ai/ { proxy_pass http://miniflux_ai:80; }`
- `location /debug/ { alias /usr/share/nginx/html/debug/; try_files ... }`
- `location / { proxy_pass http://miniflux:8080; }`

说明：
- `/miniflux-ai/` 已在仓库示例中存在：[nginx/miniflux-ai.conf](../../nginx/miniflux-ai.conf)
- `/debug/` 静态页面建议挂载到 Nginx 容器内的固定目录

### Compose 组织方式

建议采用“主 compose + 覆盖 compose”的方式，便于不同环境组合：
- `docker-compose.yml`：基础服务（miniflux/postgres/miniflux_ai）
- `docker-compose.proxy.yml`：增加 nginx，并调整端口暴露（仓库已提供）
- 后续可新增 `docker-compose.debug-ui.yml`：只负责挂载 debug 静态页面

启动示例：
- `docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d`

## 方案二：裸机（测试环境可用）

### 要点

1. Nginx 监听 `0.0.0.0:PORT`（用于局域网访问）
2. `miniflux-ai` 监听本机某端口（例如 127.0.0.1:8001）
3. `miniflux` 监听本机某端口（例如 127.0.0.1:8080）
4. Nginx 做路径反代与静态托管

### 关键配置片段（概念示例）

```
server {
  listen 80;

  location /debug/ {
    alias /var/www/debug-ui/;
    try_files $uri $uri/ /debug/index.html;
  }

  location /miniflux-ai/ {
    proxy_pass http://127.0.0.1:8001;
  }

  location / {
    proxy_pass http://127.0.0.1:8080;
  }
}
```

## 可并行实施拆分

- 网络/入口：先把 `/miniflux-ai/user/llm-pool/metrics` 通过入口打通（浏览器打开能看到 JSON）
- 静态托管：再加 `/debug/` 并确认页面可打开
- UI 开发：页面里用相对路径请求 `/miniflux-ai/*`，不依赖 Miniflux

## 联调验收清单（最小）

在同一浏览器中：
- 打开 `http://IP:PORT/miniflux-ai/user/llm-pool/metrics` 能看到 JSON
- 打开 `http://IP:PORT/miniflux-ai/user/tasks/failure-groups` 能看到 JSON
- 打开 `http://IP:PORT/debug/` 能加载页面
- 在 Debug UI 点击按钮能触发 `manual-process`、`failure-groups` 查询和重入队操作
