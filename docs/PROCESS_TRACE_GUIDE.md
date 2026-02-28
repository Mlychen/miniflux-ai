# 处理追踪功能使用指南

## 功能概述

处理追踪功能允许您详细监控手动处理条目的完整流程，包括：
- 处理进度实时追踪
- 每个处理步骤的状态
- LLM 调用详情和耗时
- 错误信息和重试情况
- 最终处理结果验证

## 快速开始

### 1. 手动触发处理

在 Debug UI 的"手动处理"卡片中：
1. 输入 Entry ID（例如：123）
2. 点击"触发处理"按钮
3. 等待处理完成

### 2. 查看处理追踪

在 Debug UI 的"处理追踪"卡片中：
1. 输入要查询的 Entry ID
2. 点击"查询"按钮
3. 查看处理流程详情

#### 处理摘要信息
- **状态**：成功/失败
- **总耗时**：整个处理流程花费的时间
- **处理阶段**：完成的处理步骤数量
- **Canonical ID**：生成的条目唯一标识
- **类别**：AI 分类结果

#### 时间线视图
按时间顺序展示每个处理步骤：
- 开始处理
- 去重检查
- 预处理（LLM 调用）
- 生成 Canonical ID
- Agent 处理（每个 Agent）
- 保存结果
- 更新 Miniflux
- 处理完成

每个步骤显示：
- 步骤名称和操作
- 时间戳
- 状态（成功/错误/跳过）
- 耗时
- 详细数据（Agent 名称、响应长度、错误信息等）

### 3. 查看处理历史

在 Debug UI 的"处理历史"卡片中：
1. 设置查询数量限制（默认 20）
2. 点击"加载"按钮
3. 查看最近的處理記錄

#### 处理历史表格列
| 列名 | 说明 |
|------|------|
| Entry ID | 条目 ID |
| Trace ID | 追踪 ID（用于关联日志） |
| 状态 | 处理结果（成功/失败） |
| 总耗时 | 整个处理流程耗时 |
| 处理阶段 | 完成的步骤数 |
| Canonical ID | 生成的唯一标识 |
| 类别 | AI 分类 |
| 开始时间 | 处理开始时间 |
| 操作 | 查看详细信息 |

## API 使用

### 获取处理追踪

```bash
GET /miniflux-ai/user/process-trace/{entry_id}
```

响应示例：
```json
{
  "status": "ok",
  "entry_id": "123",
  "trace_id": "abc123...",
  "summary": {
    "entry_id": "123",
    "trace_id": "abc123...",
    "start_time": "2026-02-28T10:30:00.000Z",
    "end_time": "2026-02-28T10:30:11.000Z",
    "total_duration_ms": 11234,
    "status": "success",
    "canonical_id": "def456...",
    "ai_category": "AI",
    "agents_processed": 3,
    "stages_count": 15
  },
  "stages": [
    {
      "timestamp": "2026-02-28T10:30:00.000Z",
      "stage": "process",
      "action": "start",
      "status": "pending",
      "data": {...}
    },
    ...
  ]
}
```

### 获取处理历史

```bash
GET /miniflux-ai/user/process-history?limit=20&offset=0
```

响应示例：
```json
{
  "status": "ok",
  "total": 100,
  "offset": 0,
  "limit": 20,
  "traces": [
    {
      "entry_id": "123",
      "trace_id": "abc123...",
      "status": "success",
      "total_duration_ms": 11234,
      "stages_count": 15,
      "canonical_id": "def456...",
      "ai_category": "AI",
      "start_time": "2026-02-28T10:30:00.000Z"
    },
    ...
  ]
}
```

## 日志文件

处理追踪日志保存在 `logs/manual-process.log`，使用 JSON 格式，每行一条记录。

### 日志字段说明

| 字段 | 说明 |
|------|------|
| timestamp | ISO 8601 格式的时间戳 |
| level | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| trace_id | 追踪 ID，关联同一次请求的所有日志 |
| entry_id | 条目 ID |
| stage | 处理阶段（process/dedup/preprocess/agent_process 等） |
| action | 操作类型（start/complete/error/skipped 等） |
| status | 状态（success/error/pending） |
| duration_ms | 耗时（毫秒） |
| data | 附加数据（不同阶段包含不同字段） |

### data 字段常见内容

| 阶段 | data 字段 |
|------|----------|
| preprocess | prompt_preview, request_preview, response_preview, ai_category |
| agent_process | agent, prompt_preview, response_preview, response_length |
| save_result | canonical_id, ai_category, agent |
| update_miniflux | content_length |
| process (complete) | canonical_id, agents_processed, agent_details |

## 故障排查

### 处理失败
1. 在"处理追踪"中查看哪个步骤标记为"错误"
2. 检查时间线中的错误信息
3. 查看 `logs/manual-process.log` 中的完整日志

### 常见问题

**问题：找不到处理记录**
- 确认 Entry ID 正确
- 确认处理已经完成
- 检查 `logs/manual-process.log` 文件是否存在

**问题：处理耗时过长**
- 检查 LLM API 响应时间
- 查看各阶段的 `duration_ms` 定位慢的步骤
- 检查是否有重试情况

**问题：Agent 处理跳过**
- 检查 Filter 配置是否正确
- 查看日志中的 `filter_matched` 原因

## 配置选项

### 日志级别
在 `common/logger.py` 中可调整日志级别：
```python
process_logger = get_process_logger(log_level='DEBUG')  # 默认 DEBUG
```

### 日志目录
默认日志保存在 `logs/` 目录，可在代码中修改：
```python
get_process_logger(log_dir='custom/logs/path')
```
