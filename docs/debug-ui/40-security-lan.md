# 40. 局域网访问与安全加固

前提：Debug UI 需要局域网可访问，这意味着入口会监听 `0.0.0.0:PORT`。此时必须假设同网段存在误访问/扫描风险。

目标：在不增加前端复杂度、不引入跨域的前提下，为 `/debug/` 与 `/miniflux-ai/` 提供最小可用的安全边界。

## 推荐的安全组合（从简到强）

### 方案 S1：CIDR 白名单（推荐）

在 Nginx 对 `/debug/` 和 `/miniflux-ai/` 增加 allow/deny：

```
location /debug/ {
  allow 192.168.1.0/24;
  deny all;
  ...
}

location /miniflux-ai/ {
  allow 192.168.1.0/24;
  deny all;
  proxy_pass http://miniflux_ai:80;
}
```

适用：局域网网段固定、访问者范围明确。

注意：
- 如果入口前还有一层反代，需要确保 Nginx 能拿到真实客户端 IP（`X-Forwarded-For`），否则 allow/deny 将基于反代 IP 判断。

### 方案 S2：Basic Auth（推荐）

对 `/debug/` 与 `/miniflux-ai/` 增加 Basic Auth：

```
auth_basic "miniflux-ai debug";
auth_basic_user_file /etc/nginx/conf.d/.htpasswd;
```

好处：
- 实现简单
- 不改后端、不改前端

缺点：
- 密码会被浏览器缓存（可控但要注意）

实践建议：
- 仅用于内网
- 配合 HTTPS（若有条件）避免明文泄露

### 方案 S3：CIDR 白名单 + Basic Auth（更推荐）

把 S1 与 S2 叠加：同网段才会进入 Basic Auth 校验。

### 方案 S4：Debug Token（备选）

如果你更偏好“脚本/页面显式传 token”，可以：
- Nginx 校验自定义 header，例如 `X-Debug-Token`
- 或把 token 写入 query（不推荐，容易出现在日志与历史记录）

原则：
- token 必须足够随机（不要用短口令）
- 不要把 token 硬编码在前端页面里（否则泄露即等价公开）

## 防误暴露建议（非常重要）

- 入口端口不要直接暴露到公网（路由器/防火墙层面限制）
- 生产环境不要开启 Debug UI；或至少默认关闭，通过 compose 覆盖文件按需启用
- Debug UI 页面不要显示或记录任何 API Key/LLM Key

## 与 Debug UI 的关系

上述安全措施都在入口（Nginx）层完成：
- Debug UI 页面仍然使用相对路径
- 不需要 CORS
- 不需要在浏览器保存敏感 token

## 最小验收

- 局域网内允许网段可打开 `http://IP:PORT/debug/`
- 非允许网段访问直接被拒绝（403/401）
- Debug UI 操作接口均可用（manual-process/metrics/failed-entries/clear）
