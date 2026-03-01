# Logging 过滤与排查速查（Task 架构）

> 适用于当前“持久化任务 + TaskWorker”主链路。

## 1. 快速看主链路节奏

关键日志：
- `Successfully connected to Miniflux!`
- `Get unread entries via webhook:`
- `Webhook tasks persisted accepted=`
- `TaskWorker.start:`
- `TaskWorker.task_result`

PowerShell 示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "Successfully connected to Miniflux!", `
    "Get unread entries via webhook", `
    "Webhook tasks persisted accepted=", `
    "TaskWorker.start:", `
    "TaskWorker.task_result"
```

## 2. 入站与持久化排查（Webhook）

关注点：
- 签名错误是否大量出现（应返回 403）
- 持久化是否成功（`accepted/duplicates`）
- 是否出现 `task persistence failed`

示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "webhook: payload_length=", `
    "Get unread entries via webhook", `
    "Webhook tasks persisted accepted=", `
    "Webhook task persistence failed"
```

## 3. Worker 健康度排查

关注点：
- worker 是否正常启动
- claim 是否异常
- 任务结果分布（done/retryable/dead）

示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "TaskWorker.start:", `
    "TaskWorker.claim_tasks", `
    "TaskWorker.task_result"
```

按状态统计：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String "TaskWorker.task_result" |
  ForEach-Object { $_.Line } |
  Group-Object |
  Select-Object Name,Count |
  Sort-Object Count -Descending
```

## 4. 任务失败热点排查

建议直接用 API 聚类查看，而不是手工扫全日志：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8081/miniflux-ai/user/tasks/failure-groups?limit=50" |
  ConvertTo-Json -Depth 8
```

查看某分组样本：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8081/miniflux-ai/user/tasks/failure-groups/tasks?status=dead&error_key=(empty)&limit=20" |
  ConvertTo-Json -Depth 8
```

## 5. 处理追踪与内容链路

关键日志：
- `process_entry: start entry_id=`
- `process_entry: updated entry`
- `manual-process:`

示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "manual-process:", `
    "process_entry: start entry_id=", `
    "process_entry: updated entry"
```

## 6. LLM 调用异常

关键日志：
- `Error in get_result`
- `Error processing entry`
- `LLMRequestPool: entry_call_failed`

示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "Error in get_result", `
    "Error processing entry", `
    "LLMRequestPool: entry_call_failed"
```

## 7. 快速窗口查看

```powershell
Get-Content .\miniflux-ai.log -Tail 5000 |
  Select-String -Pattern `
    "webhook:", `
    "TaskWorker.", `
    "process_entry:"
```

