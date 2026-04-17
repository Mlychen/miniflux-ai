/**
 * LLM 调用记录模块
 */

import {
  request,
  prettyPrint,
  API,
  formatTime,
  formatDuration,
  truncateIdentifier,
  escapeHtml
} from '../api/index.js';
import { getLLMCalls, getLLMCallDuplicates } from '../api/index.js';
import { getStatusBadge, showEmptyTableRow } from './ui.js';

/**
 * 截断文本
 * @param {string} text - 原始文本
 * @param {number} maxLen - 最大长度
 * @returns {string} 截断后的文本
 */
function truncateText(text, maxLen = 50) {
  if (!text) return '-';
  const escaped = escapeHtml(text);
  if (escaped.length <= maxLen) return escaped;
  return escaped.substring(0, maxLen) + '...';
}

/**
 * 初始化 LLM 调用记录模块
 * @param {Object} options - 配置选项
 */
export function initLLMCalls(options) {
  const {
    loadBtn,
    tableBody,
    outputEl,
    canonicalIdInput,
    agentFilter,
    statusFilter,
    limitInput,
    statsEl,
    duplicatesResultEl,
    onTraceRequest
  } = options;

  let currentCalls = [];

  /**
   * 渲染 LLM 调用记录表格
   * @param {Array} calls - 调用记录列表
   */
  function renderTable(calls) {
    tableBody.innerHTML = '';
    if (!calls || calls.length === 0) {
      tableBody.appendChild(showEmptyTableRow(8, '📭', '暂无 LLM 调用记录'));
      return;
    }

    calls.forEach(function (call) {
      const tr = document.createElement('tr');

      // 时间
      const tdTime = document.createElement('td');
      tdTime.className = 'mono';
      tdTime.style.fontSize = '12px';
      tdTime.textContent = formatTime(call.timestamp);
      tr.appendChild(tdTime);

      // Canonical ID (可点击)
      const tdCanonical = document.createElement('td');
      tdCanonical.className = 'mono';
      tdCanonical.style.fontSize = '12px';
      const canonicalId = call.canonical_id || '-';
      if (canonicalId && canonicalId !== '-') {
        const a = document.createElement('a');
        a.href = '#';
        a.className = 'link';
        a.textContent = truncateIdentifier(canonicalId, 16);
        a.title = canonicalId;
        a.addEventListener('click', function (e) {
          e.preventDefault();
          if (onTraceRequest) {
            onTraceRequest(canonicalId);
          }
        });
        tdCanonical.appendChild(a);
      } else {
        tdCanonical.textContent = '-';
      }
      tr.appendChild(tdCanonical);

      // Trace ID
      const tdTrace = document.createElement('td');
      tdTrace.className = 'mono';
      tdTrace.style.fontSize = '12px';
      const traceId = call.trace_id || '';
      if (traceId) {
        tdTrace.textContent = traceId.substring(0, 8) + '...';
        tdTrace.title = traceId;
      } else {
        tdTrace.textContent = '-';
      }
      tr.appendChild(tdTrace);

      // Agent/Stage
      const tdAgent = document.createElement('td');
      const agent = call.agent || call.stage || '-';
      tdAgent.innerHTML = `<span class="badge badge-info">${escapeHtml(agent)}</span>`;
      tr.appendChild(tdAgent);

      // 状态
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getStatusBadge(call.status);
      tr.appendChild(tdStatus);

      // 耗时
      const tdDuration = document.createElement('td');
      tdDuration.className = 'mono';
      tdDuration.textContent = formatDuration(call.duration_ms);
      tr.appendChild(tdDuration);

      // 响应预览
      const tdResponse = document.createElement('td');
      tdResponse.className = 'mono';
      tdResponse.style.fontSize = '12px';
      tdResponse.style.maxWidth = '200px';
      tdResponse.textContent = truncateText(call.raw_response, 50);
      tr.appendChild(tdResponse);

      // 操作
      const tdOp = document.createElement('td');
      const detailBtn = document.createElement('button');
      detailBtn.className = 'btn';
      detailBtn.textContent = '详情';
      detailBtn.addEventListener('click', function () {
        showCallDetail(call);
      });
      tdOp.appendChild(detailBtn);
      tr.appendChild(tdOp);

      tableBody.appendChild(tr);
    });
  }

  /**
   * 显示调用详情弹窗
   * @param {Object} call - 调用记录
   */
  function showCallDetail(call) {
    // 创建弹窗
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1000;display:flex;align-items:center;justify-content:center;';

    const content = document.createElement('div');
    content.className = 'modal-content';
    content.style.cssText = 'background:#ffffff;border-radius:var(--radius-md);max-width:900px;max-height:80vh;overflow:auto;padding:var(--space-lg);color:#24292f;box-shadow:0 8px 32px rgba(0,0,0,0.3);';

    content.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-md);">
        <h3 style="margin:0;color:#24292f;">LLM 调用详情</h3>
        <button class="btn" id="closeModal">关闭</button>
      </div>
      <div class="stats-row" style="margin-bottom:var(--space-md);">
        <div class="stat"><span class="stat-label">时间</span><span class="stat-value">${formatTime(call.timestamp)}</span></div>
        <div class="stat"><span class="stat-label">状态</span><span class="stat-value">${getStatusBadge(call.status)}</span></div>
        <div class="stat"><span class="stat-label">耗时</span><span class="stat-value">${formatDuration(call.duration_ms)}</span></div>
      </div>
      <div style="margin-bottom:var(--space-sm);font-size:13px;color:#24292f;">
        <strong>Trace ID:</strong> <span class="mono">${escapeHtml(call.trace_id || '-')}</span><br>
        <strong>Entry ID:</strong> <span class="mono">${escapeHtml(call.entry_id || '-')}</span><br>
        <strong>Canonical ID:</strong> <span class="mono">${escapeHtml(call.canonical_id || '-')}</span><br>
        <strong>Agent:</strong> <span class="mono">${escapeHtml(call.agent || call.stage || '-')}</span>
      </div>
      <div style="margin-bottom:var(--space-md);">
        <details style="margin-bottom:var(--space-sm);">
          <summary style="cursor:pointer;font-weight:500;color:#24292f;">Prompt Template</summary>
          <pre class="code-block mono" style="margin-top:var(--space-xs);max-height:200px;overflow:auto;">${escapeHtml(call.prompt_template || '-')}</pre>
        </details>
        <details style="margin-bottom:var(--space-sm);">
          <summary style="cursor:pointer;font-weight:500;color:#24292f;">Input Text</summary>
          <pre class="code-block mono" style="margin-top:var(--space-xs);max-height:200px;overflow:auto;">${escapeHtml(call.input_text || '-')}</pre>
        </details>
        <details>
          <summary style="cursor:pointer;font-weight:500;color:#24292f;">Raw Response</summary>
          <pre class="code-block mono" style="margin-top:var(--space-xs);max-height:200px;overflow:auto;">${escapeHtml(call.raw_response || '-')}</pre>
        </details>
      </div>
    `;

    modal.appendChild(content);
    document.body.appendChild(modal);

    // 关闭事件
    modal.addEventListener('click', function (e) {
      if (e.target === modal) {
        document.body.removeChild(modal);
      }
    });

    content.querySelector('#closeModal').addEventListener('click', function () {
      document.body.removeChild(modal);
    });
  }

  /**
   * 更新统计信息
   */
  function updateStats() {
    const total = currentCalls.length;
    const successCount = currentCalls.filter(c => c.status === 'success').length;
    const errorCount = currentCalls.filter(c => c.status === 'error').length;

    if (statsEl) {
      statsEl.innerHTML = `
        <div class="stat"><span class="stat-label">总数</span><span class="stat-value">${total}</span></div>
        <div class="stat"><span class="stat-label">成功</span><span class="stat-value" style="color:var(--success);">${successCount}</span></div>
        <div class="stat"><span class="stat-label">失败</span><span class="stat-value" style="color:var(--danger);">${errorCount}</span></div>
      `;
    }
  }

  /**
   * 加载 LLM 调用记录
   */
  async function loadCalls() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    loadBtn.textContent = '加载中...';

    // 隐藏重复检测结果容器
    if (duplicatesResultEl) {
      duplicatesResultEl.style.display = 'none';
    }

    const params = {
      limit: parseInt((limitInput?.value || '100').trim(), 10) || 100
    };

    const canonicalId = (canonicalIdInput?.value || '').trim();
    if (canonicalId) params.canonical_id = canonicalId;

    const agent = (agentFilter?.value || '').trim();
    if (agent) params.agent = agent;

    const status = (statusFilter?.value || '').trim();
    if (status) params.status = status;

    try {
      const data = await getLLMCalls(params);
      currentCalls = data.calls || [];
      outputEl.textContent = prettyPrint({ status: data.status, total: data.total, count: data.count });
      renderTable(currentCalls);
      updateStats();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = '加载';
    }
  }

  // 绑定事件
  if (loadBtn) {
    loadBtn.addEventListener('click', loadCalls);
  }

  // 支持回车键触发加载
  if (canonicalIdInput) {
    canonicalIdInput.addEventListener('keypress', function (e) {
      if (e.key === 'Enter') {
        loadCalls();
      }
    });
  }

  return { loadCalls, renderTable };
}

/**
 * 初始化重复调用检测模块
 * @param {Object} options - 配置选项
 */
export function initLLMDuplicates(options) {
  const {
    loadBtn,
    tableBody,
    resultContainer,
    outputEl,
    onCanonicalClick
  } = options;

  async function loadDuplicates() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    loadBtn.textContent = '检测中...';

    try {
      const data = await getLLMCallDuplicates();
      const duplicates = data.duplicates || [];
      outputEl.textContent = prettyPrint({ status: data.status, count: duplicates.length });

      tableBody.innerHTML = '';
      if (duplicates.length === 0) {
        // 没有重复时隐藏结果容器
        if (resultContainer) {
          resultContainer.style.display = 'none';
        }
        tableBody.appendChild(showEmptyTableRow(5, '✅', '未发现重复调用'));
        // 显示结果容器以展示空结果提示
        if (resultContainer) {
          resultContainer.style.display = 'block';
        }
        return;
      }

      // 有重复数据时显示结果容器
      if (resultContainer) {
        resultContainer.style.display = 'block';
      }

      duplicates.forEach(function (dup) {
        const tr = document.createElement('tr');

        // Canonical ID
        const tdCanonical = document.createElement('td');
        tdCanonical.className = 'mono';
        tdCanonical.style.fontSize = '12px';
        const canonicalId = dup.canonical_id || '';
        if (canonicalId && onCanonicalClick) {
          const a = document.createElement('a');
          a.href = '#';
          a.className = 'link';
          a.textContent = truncateIdentifier(canonicalId, 16);
          a.title = canonicalId;
          a.addEventListener('click', function (e) {
            e.preventDefault();
            onCanonicalClick(canonicalId);
          });
          tdCanonical.appendChild(a);
        } else {
          tdCanonical.textContent = truncateIdentifier(canonicalId, 16);
        }
        tr.appendChild(tdCanonical);

        // 调用次数
        const tdCount = document.createElement('td');
        tdCount.innerHTML = `<span class="badge badge-warning">${dup.call_count}</span>`;
        tr.appendChild(tdCount);

        // 首次调用
        const tdFirst = document.createElement('td');
        tdFirst.className = 'mono';
        tdFirst.style.fontSize = '12px';
        tdFirst.textContent = formatTime(dup.first_call);
        tr.appendChild(tdFirst);

        // 最后调用
        const tdLast = document.createElement('td');
        tdLast.className = 'mono';
        tdLast.style.fontSize = '12px';
        tdLast.textContent = formatTime(dup.last_call);
        tr.appendChild(tdLast);

        // Agents
        const tdAgents = document.createElement('td');
        tdAgents.innerHTML = (dup.agents || []).map(a => `<span class="badge badge-info">${escapeHtml(a)}</span>`).join(' ');
        tr.appendChild(tdAgents);

        tableBody.appendChild(tr);
      });

    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = '检测重复';
    }
  }

  if (loadBtn) {
    loadBtn.addEventListener('click', loadDuplicates);
  }

  return { loadDuplicates };
}

/**
 * 初始化 LLM 指标模块 (保留兼容性)
 * @param {Object} options - 配置选项
 */
export function initLLMMetrics(options) {
  const {
    loadBtn,
    outputEl
  } = options;

  async function loadMetrics() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    loadBtn.innerHTML = '<div class="spinner"></div> 加载中...';

    try {
      const data = await request('GET', API.llmMetrics);
      outputEl.textContent = prettyPrint(data);
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      loadBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M11.536 3.464a5 5 0 010 7.072.5.5 0 11-.708-.707 4 4 0 000-5.656.5.5 0 11.708-.708z"/>
          <path d="M15 8a6 6 0 11-12 0 6 6 0 0112 0z"/>
          <path d="M8 3a.5.5 0 01.5.5v4a.5.5 0 01-1 0v-4A.5.5 0 018 3z"/>
        </svg>
        刷新指标
      `;
    }
  }

  loadBtn.addEventListener('click', loadMetrics);

  return { loadMetrics };
}

/**
 * 初始化失败条目模块
 * @param {Object} options - 配置选项
 */
export function initFailedEntries(options) {
  const {
    loadBtn,
    clearAllBtn,
    outputEl,
    tableBody,
    limitInput,
    onMetricsRefresh,
    onTraceRequest
  } = options;

  function renderFailedItems(items) {
    tableBody.innerHTML = '';
    if (!items || items.length === 0) {
      tableBody.appendChild(showEmptyTableRow(8, '✅', '暂无失败条目'));
      return;
    }

    items.forEach(function (it) {
      const tr = document.createElement('tr');

      // Canonical ID (可点击跳转 trace)
      const tdCanonical = document.createElement('td');
      tdCanonical.className = 'mono';
      tdCanonical.style.fontSize = '12px';
      const canonicalId = it.canonical_id || '';
      if (canonicalId && onTraceRequest) {
        const a = document.createElement('a');
        a.href = '#';
        a.className = 'link';
        a.textContent = truncateIdentifier(canonicalId, 16);
        a.title = canonicalId;
        a.addEventListener('click', function (e) {
          e.preventDefault();
          onTraceRequest(canonicalId);
        });
        tdCanonical.appendChild(a);
      } else {
        tdCanonical.textContent = canonicalId || '-';
      }
      tr.appendChild(tdCanonical);

      // Status
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getStatusBadge(it.status);
      tr.appendChild(tdStatus);

      // Attempts
      const tdAttempts = document.createElement('td');
      tdAttempts.className = 'mono';
      tdAttempts.textContent = `${it.attempts || 0}/${it.max_attempts || '?'}`;
      tr.appendChild(tdAttempts);

      // Created
      const tdCreated = document.createElement('td');
      tdCreated.textContent = it.created_at ? new Date(it.created_at).toLocaleString('zh-CN') : '-';
      tr.appendChild(tdCreated);

      // Updated
      const tdUpdated = document.createElement('td');
      tdUpdated.textContent = it.updated_at ? new Date(it.updated_at).toLocaleString('zh-CN') : '-';
      tr.appendChild(tdUpdated);

      // Next Retry / Error
      const tdError = document.createElement('td');
      tdError.className = 'mono';
      tdError.style.fontSize = '12px';
      if (it.last_error) {
        tdError.textContent = truncateText(it.last_error, 40);
        tdError.title = it.last_error;
      } else if (it.next_retry_at) {
        tdError.textContent = '下次重试: ' + new Date(it.next_retry_at).toLocaleString('zh-CN');
      } else {
        tdError.textContent = '-';
      }
      tr.appendChild(tdError);

      // URL
      const tdUrl = document.createElement('td');
      if (it.url) {
        const a = document.createElement('a');
        a.href = it.url;
        a.target = '_blank';
        a.rel = 'noreferrer';
        a.textContent = '打开';
        a.className = 'link';
        tdUrl.appendChild(a);
      } else {
        tdUrl.textContent = '-';
      }
      tr.appendChild(tdUrl);

      // Actions
      const tdOp = document.createElement('td');

      const resetBtn = document.createElement('button');
      resetBtn.className = 'btn';
      resetBtn.textContent = '重试';
      resetBtn.addEventListener('click', async function () {
        resetBtn.disabled = true;
        resetBtn.textContent = '重试中...';

        try {
          const data = await request('POST', API.llmClear, { task_id: it.task_id });
          outputEl.textContent = prettyPrint(data);
          loadFailedItems();
          if (onMetricsRefresh) onMetricsRefresh();
        } catch (e) {
          outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
        } finally {
          resetBtn.disabled = false;
          resetBtn.textContent = '重试';
        }
      });

      const traceBtn = document.createElement('button');
      traceBtn.className = 'btn';
      traceBtn.textContent = 'Trace';
      traceBtn.style.marginLeft = '4px';
      traceBtn.addEventListener('click', function () {
        if (onTraceRequest) {
          onTraceRequest(it.canonical_id || '');
        }
      });

      tdOp.appendChild(resetBtn);
      tdOp.appendChild(traceBtn);
      tr.appendChild(tdOp);

      tableBody.appendChild(tr);
    });
  }

  async function loadFailedItems() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    loadBtn.textContent = '加载中...';

    const n = parseInt((limitInput.value || '100').trim(), 10) || 100;

    try {
      const data = await request('GET', `${API.llmFailedEntries}?limit=${encodeURIComponent(n)}`);
      outputEl.textContent = prettyPrint({ status: data.status, count: (data.items || []).length });
      renderFailedItems(data.items || []);
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      loadBtn.textContent = '加载';
    }
  }

  async function clearAll() {
    outputEl.textContent = '';
    clearAllBtn.disabled = true;
    clearAllBtn.textContent = '重试中...';

    try {
      const data = await request('POST', API.llmClear, {});
      outputEl.textContent = prettyPrint(data);
      loadFailedItems();
      if (onMetricsRefresh) onMetricsRefresh();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      clearAllBtn.disabled = false;
      clearAllBtn.textContent = '批量重试';
    }
  }

  loadBtn.addEventListener('click', loadFailedItems);
  clearAllBtn.addEventListener('click', clearAll);

  return { loadFailedItems };
}
