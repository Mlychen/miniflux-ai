/**
 * LLM 指标与失败条目模块
 */

import {
  request,
  prettyPrint,
  API
} from '../api/index.js';
import { getStatusBadge, showEmptyTableRow } from './ui.js';

/**
 * 初始化 LLM 指标模块
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

      // Entry Key
      const tdKey = document.createElement('td');
      tdKey.className = 'mono';
      tdKey.style.fontSize = '12px';
      tdKey.textContent = it.entry_key;
      tr.appendChild(tdKey);

      // Status
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getStatusBadge(it.status);
      tr.appendChild(tdStatus);

      // Attempts
      const tdAttempts = document.createElement('td');
      tdAttempts.className = 'mono';
      tdAttempts.textContent = `${it.attempts_used || 0}/${it.max_attempts || '?'}`;
      tr.appendChild(tdAttempts);

      // Created
      const tdCreated = document.createElement('td');
      tdCreated.textContent = it.created_at ? new Date(it.created_at).toLocaleString('zh-CN') : '-';
      tr.appendChild(tdCreated);

      // Last Attempt
      const tdLast = document.createElement('td');
      tdLast.textContent = it.last_attempt_at ? new Date(it.last_attempt_at).toLocaleString('zh-CN') : '-';
      tr.appendChild(tdLast);

      // TTL
      const tdTtl = document.createElement('td');
      tdTtl.className = 'mono';
      tdTtl.textContent = it.ttl_seconds != null ? `${it.ttl_seconds}s` : '-';
      tr.appendChild(tdTtl);

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
      resetBtn.textContent = '重置';
      resetBtn.addEventListener('click', async function () {
        resetBtn.disabled = true;
        resetBtn.textContent = '重置中...';

        try {
          const data = await request('POST', API.llmClear, { entry_key: it.entry_key });
          outputEl.textContent = prettyPrint(data);
          loadFailedItems();
          if (onMetricsRefresh) onMetricsRefresh();
        } catch (e) {
          outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
        } finally {
          resetBtn.disabled = false;
          resetBtn.textContent = '重置';
        }
      });

      const traceBtn = document.createElement('button');
      traceBtn.className = 'btn';
      traceBtn.textContent = 'Trace';
      traceBtn.style.marginLeft = '4px';
      traceBtn.addEventListener('click', function () {
        if (onTraceRequest) {
          onTraceRequest(it.entry_key || '');
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
    clearAllBtn.textContent = '清空中...';

    try {
      const data = await request('POST', API.llmClear, {});
      outputEl.textContent = prettyPrint(data);
      loadFailedItems();
      if (onMetricsRefresh) onMetricsRefresh();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      clearAllBtn.disabled = false;
      clearAllBtn.textContent = '清空池';
    }
  }

  loadBtn.addEventListener('click', loadFailedItems);
  clearAllBtn.addEventListener('click', clearAll);

  return { loadFailedItems };
}