 # Logging 过滤与排查速查

> 适用于开启 `log_level: "DEBUG"` 时，对接真实 Miniflux 持续运行后一段时间的日志分析与排查。

## 1. 快速看整体链路节奏

- 目标：先大致感受服务在干什么：轮询、webhook、AI News 生成是否有节奏。
- 典型关键字：
  - `Get unread entries via webhook`
  - `Get unread entries:`
  - `Generating daily news`
  - `Generated daily news successfully`
  - `Cleared entries.json`
  - `Successfully connected to Miniflux!`

PowerShell 示例：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String -Pattern `
    "Get unread entries via webhook", `
    "Get unread entries:", `
    "Generating daily news", `
    "Generated daily news successfully", `
    "Cleared entries.json", `
    "Successfully connected to Miniflux!"
```

## 2. 分析入口负载（轮询 + webhook）

- 轮询入口统计：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String "Get unread entries:" |
  Group-Object Line |
  Select-Object Name,Count |
  Sort-Object Count -Descending
```

- webhook 入口统计：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String "Get unread entries via webhook" |
  Group-Object Line |
  Select-Object Name,Count |
  Sort-Object Count -Descending
```

- 若开启 DEBUG，可查看批次详情与样例 ID：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "fetch_unread_entries: fetched ", `
    "fetch_unread_entries: sample entry ids", `
    "webhook: batch_entries_count="
```

## 3. 队列健康度（webhook 模式）

- 观察队列状态、入队与消费：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "WebhookQueue.enqueue:", `
    "WebhookQueue._consumer_loop:", `
    "WebhookQueue.start:", `
    "WebhookQueue.stop:"
```

- 查看队列满/拒绝情况：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String "Webhook queue is full, rejecting request", "queue full"
```

## 4. 单条 entry 处理与去重效果

- 观察处理路径与去重：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "process_entry: start entry_id=", `
    "Skipping entry ", `
    "agents:", `
    "process_entry: agent=", `
    "process_entry: updated entry "
```

- 追踪某个具体 entry（以 `entry_id=123` 为例）：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String "entry_id=123", "feed_id:123"
```

## 5. LLM 调用状况

- 集中查看错误与异常：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "Error in get_result", `
    "Error processing entry", `
    "Error generating daily news"
```

- 查看 LLM 返回长度（DEBUG 模式）：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "process_entry: agent=", `
    "generate_daily_news: greeting_length=", `
    "generate_daily_news: summary_block_length=", `
    "generate_daily_news: summary_length="
```

## 6. AI News 生成链路

- 观察每日新闻生成节奏、输入输出体量：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "Generating daily news", `
    "No entries to generate daily news", `
    "generate_daily_news: entries_count=", `
    "generate_daily_news: concatenated_content_length=", `
    "generate_daily_news: greeting_length=", `
    "generate_daily_news: summary_block_length=", `
    "generate_daily_news: summary_length=", `
    "generate_daily_news: saved_content_length=", `
    "Generated daily news successfully", `
    "Cleared entries.json", `
    "Successfully refreshed the ai_news feed in Miniflux!"
```

## 7. 错误与异常高峰排查

- 所有 ERROR：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String " ERROR " |
  Sort-Object -Property LineNumber
```

- 按错误类型粗分统计：

```powershell
Get-Content .\miniflux-ai.log |
  Select-String `
    "Error processing entry", `
    "Error generating daily news", `
    "Cannot connect to Miniflux", `
    "Error processing webhook item" |
  Group-Object Pattern |
  Select-Object Name,Count
```

## 8. 按时间窗口近似查看

- 日志很大时，可先用 `-Tail` 做近似时间窗口，例如最近 N 行：

```powershell
Get-Content .\miniflux-ai.log -Tail 5000 |
  Select-String `
    "generate_daily_news", `
    "Get unread entries", `
    "webhook:"
```

> 提示：如果未来将日志写入集中日志系统（如 ELK / Loki），可以直接用本指南中的关键字段作为查询条件，构造视图或告警。 

