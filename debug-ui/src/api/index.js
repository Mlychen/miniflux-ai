/**
 * API 封装模块 - 统一管理 HTTP 请求
 *
 * 语义说明：
 * - trace_id: 处理链路 ID，用于聚合一次处理请求产生的所有任务和日志
 * - canonical_id: 条目逻辑唯一标识（按 URL+title 生成）
 * - entry_id: Miniflux 原始条目 ID
 */

// 请求状态回调
let onStatusChange = null;

/**
 * 设置状态变化回调函数
 * @param {Function} callback - 回调函数 (method, url, status, ms) => void
 */
export function setStatusCallback(callback) {
  onStatusChange = callback;
}

/**
 * 格式化对象为 JSON 字符串
 * @param {any} obj - 要格式化的对象
 * @returns {string} 格式化后的 JSON 字符串
 */
export function prettyPrint(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch (e) {
    return String(obj);
  }
}

/**
 * 生成随机 Trace ID（32 位 hex 字符串）
 * @returns {string} UUID v4 hex 格式的 trace_id
 */
export function generateTraceId() {
  return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

/**
 * 发起 HTTP 请求
 * @param {string} method - HTTP 方法
 * @param {string} url - 请求 URL
 * @param {any} body - 请求体（可选）
 * @returns {Promise<any>} 响应数据
 */
export async function request(method, url, body) {
  const start = performance.now();
  const options = {
    method,
    headers: {}
  };

  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  const ms = Math.round(performance.now() - start);
  const text = await response.text();

  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (e) {
    data = { raw: text };
  }

  // 触发状态回调
  if (onStatusChange) {
    onStatusChange(method, url, response.status, ms);
  }

  if (!response.ok) {
    const error = new Error('HTTP ' + response.status);
    error.response = data;
    throw error;
  }

  return data;
}

/**
 * 解析正整数
 * @param {string} raw - 原始字符串
 * @param {number} fallback - 默认值
 * @returns {number} 解析后的正整数
 */
export function parsePositiveInt(raw, fallback) {
  const n = parseInt((raw || '').trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * 格式化时间戳
 * @param {string} timestamp - ISO 时间字符串
 * @returns {string} 本地化时间字符串
 */
export function formatTime(timestamp) {
  if (!timestamp) return '-';
  try {
    return new Date(timestamp).toLocaleString('zh-CN');
  } catch (e) {
    return timestamp;
  }
}

/**
 * 格式化 Unix 秒级时间戳
 * @param {number} v - Unix 秒级时间戳
 * @returns {string} 本地化时间字符串
 */
export function formatUnixSeconds(v) {
  if (v === null || v === undefined || v === '') {
    return '-';
  }
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) {
    return '-';
  }
  return new Date(n * 1000).toLocaleString('zh-CN');
}

/**
 * 格式化持续时间
 * @param {number} ms - 毫秒数
 * @returns {string} 格式化后的持续时间
 */
export function formatDuration(ms) {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return Math.round(ms) + 'ms';
  return (ms / 1000).toFixed(2) + 's';
}

/**
 * HTML 转义
 * @param {string} value - 原始字符串
 * @returns {string} 转义后的字符串
 */
export function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ============ API 端点 ============

const API_BASE = '/miniflux-ai';

export const API = {
  // 手动处理
  manualProcess: `${API_BASE}/manual-process`,

  // 处理追踪
  processTrace: (id) => `${API_BASE}/user/process-trace/${encodeURIComponent(id)}`,
  processHistory: `${API_BASE}/user/process-history`,
  processSearch: `${API_BASE}/user/process-search`,
  canonicalTrace: (canonicalId, traceId) => {
    const url = `${API_BASE}/user/canonical-trace/${encodeURIComponent(canonicalId)}`;
    if (traceId) {
      return `${url}?trace_id=${encodeURIComponent(traceId)}`;
    }
    return url;
  },

  // 任务管理
  tasks: `${API_BASE}/user/tasks`,
  taskDetail: (taskId) => `${API_BASE}/user/tasks/${encodeURIComponent(taskId)}`,
  taskMetrics: `${API_BASE}/user/tasks/metrics`,
  failureGroups: `${API_BASE}/user/tasks/failure-groups`,
  failureGroupTasks: `${API_BASE}/user/tasks/failure-groups/tasks`,
  requeueGroup: `${API_BASE}/user/tasks/failure-groups/requeue`,
  requeueTask: (taskId) => `${API_BASE}/user/tasks/${encodeURIComponent(taskId)}/requeue`,

  // LLM 池
  llmMetrics: `${API_BASE}/user/llm-pool/metrics`,
  llmFailedEntries: `${API_BASE}/user/llm-pool/failed-entries`,
  llmClear: `${API_BASE}/user/llm-pool/clear`,

  // LLM 调用记录
  llmCalls: `${API_BASE}/user/llm-calls`,
  llmCallsDuplicates: `${API_BASE}/user/llm-calls/duplicates`,

  // 已处理条目
  processedEntries: `${API_BASE}/user/processed-entries`,

  // Miniflux
  minifluxMe: `${API_BASE}/user/miniflux/me`,
  minifluxEntry: (entryId) => `${API_BASE}/user/miniflux/entry/${entryId}`,
};

// ============ API 方法封装 ============

/**
 * 触发手动处理
 * @param {number|string} entryId - 条目 ID
 * @param {string} traceId - 可选的 trace_id
 * @returns {Promise<any>} 处理结果
 */
export async function triggerManualProcess(entryId, traceId) {
  const payload = { entry_id: entryId };
  if (traceId) {
    payload.trace_id = traceId;
  }
  return request('POST', API.manualProcess, payload);
}

/**
 * 获取处理追踪详情
 * @param {string} id - Trace ID 或 Entry ID
 * @returns {Promise<any>} 追踪数据
 */
export async function getProcessTrace(id) {
  return request('GET', API.processTrace(id));
}

/**
 * 获取处理历史
 * @param {number} limit - 限制数量
 * @returns {Promise<any>} 历史数据
 */
export async function getProcessHistory(limit = 20) {
  return request('GET', `${API.processHistory}?limit=${encodeURIComponent(limit)}`);
}

/**
 * 获取任务列表
 * @param {Object} params - 查询参数
 * @returns {Promise<any>} 任务列表
 */
export async function getTasks(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set('status', params.status);
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));
  if (params.trace_id) searchParams.set('trace_id', params.trace_id);
  if (params.error) searchParams.set('error', params.error);

  const queryString = searchParams.toString();
  return request('GET', queryString ? `${API.tasks}?${queryString}` : API.tasks);
}

/**
 * 获取任务详情
 * @param {number} taskId - 任务 ID
 * @returns {Promise<any>} 任务详情
 */
export async function getTaskDetail(taskId) {
  return request('GET', API.taskDetail(taskId));
}

/**
 * 重入队单个任务
 * @param {number} taskId - 任务 ID
 * @returns {Promise<any>} 操作结果
 */
export async function requeueTask(taskId) {
  return request('POST', API.requeueTask(taskId), {});
}

/**
 * 获取失败分组
 * @param {Object} params - 查询参数
 * @returns {Promise<any>} 失败分组数据
 */
export async function getFailureGroups(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set('status', params.status);
  if (params.error) searchParams.set('error', params.error);
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));

  const queryString = searchParams.toString();
  return request('GET', queryString ? `${API.failureGroups}?${queryString}` : API.failureGroups);
}

/**
 * 获取失败分组的任务
 * @param {Object} params - 查询参数
 * @returns {Promise<any>} 任务列表
 */
export async function getFailureGroupTasks(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set('status', params.status);
  if (params.error_key) searchParams.set('error_key', params.error_key);
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));
  if (params.include_payload) searchParams.set('include_payload', 'true');

  return request('GET', `${API.failureGroupTasks}?${searchParams.toString()}`);
}

/**
 * 重入队失败分组
 * @param {Object} params - 参数 { status, error_key, limit }
 * @returns {Promise<any>} 操作结果
 */
export async function requeueFailureGroup(params) {
  return request('POST', API.requeueGroup, {
    status: params.status,
    error_key: params.error_key,
    limit: params.limit || 100,
  });
}

/**
 * 获取 LLM 池指标
 * @returns {Promise<any>} 指标数据
 */
export async function getLLMMetrics() {
  return request('GET', API.llmMetrics);
}

/**
 * 获取失败条目
 * @param {number} limit - 限制数量
 * @returns {Promise<any>} 失败条目数据
 */
export async function getFailedEntries(limit = 100) {
  return request('GET', `${API.llmFailedEntries}?limit=${encodeURIComponent(limit)}`);
}

/**
 * 清空 LLM 池 / 重试任务
 * @param {number} taskId - 可选的任务 ID，用于重试单个任务
 * @returns {Promise<any>} 操作结果
 */
export async function clearLLMPool(taskId = null) {
  const payload = taskId ? { task_id: taskId } : {};
  return request('POST', API.llmClear, payload);
}

/**
 * 获取已处理条目
 * @param {number} limit - 限制数量
 * @param {number} offset - 偏移量
 * @returns {Promise<any>} 已处理条目数据
 */
export async function getProcessedEntries(limit = 100, offset = 0) {
  return request('GET', `${API.processedEntries}?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`);
}

/**
 * 搜索处理历史
 * @param {string} query - 搜索关键词（entry_id 或 canonical_id）
 * @param {number} limit - 限制数量
 * @returns {Promise<any>} 搜索结果
 */
export async function searchProcessHistory(query, limit = 50) {
  return request('GET', `${API.processSearch}?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}`);
}

/**
 * 获取 LLM 调用记录
 * @param {Object} params - 查询参数
 * @returns {Promise<any>} LLM 调用记录
 */
export async function getLLMCalls(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.limit) searchParams.set('limit', String(params.limit));
  if (params.offset) searchParams.set('offset', String(params.offset));
  if (params.canonical_id) searchParams.set('canonical_id', params.canonical_id);
  if (params.trace_id) searchParams.set('trace_id', params.trace_id);
  if (params.agent) searchParams.set('agent', params.agent);
  if (params.status) searchParams.set('status', params.status);

  const queryString = searchParams.toString();
  return request('GET', queryString ? `${API.llmCalls}?${queryString}` : API.llmCalls);
}

/**
 * 获取 LLM 重复调用记录
 * @returns {Promise<any>} 重复调用记录
 */
export async function getLLMCallDuplicates() {
  return request('GET', API.llmCallsDuplicates);
}
