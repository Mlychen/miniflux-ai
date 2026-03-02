/**
 * 已处理条目模块
 *
 * 语义说明：
 * - trace_id: 处理链路 ID
 * - canonical_id: 条目逻辑唯一标识
 * - entry_id: Miniflux 原始条目 ID
 */

import {
  request,
  prettyPrint,
  formatTime,
  formatDuration,
  API
} from '../api/index.js';
import { getCategoryBadge, showEmptyTableRow, getStatusBadgeClass } from './ui.js';
import { searchProcessHistory } from '../api/index.js';
import { renderTimeline } from './traces.js';

/**
 * 初始化已处理条目模块
 * @param {Object} options - 配置选项
 */
export function initProcessedEntries(options) {
  const {
    loadBtn,
    refreshBtn,
    outputEl,
    tableBody,
    totalEl,
    rangeEl,
    countEl,
    limitInput,
    offsetInput,
    onTraceRequest
  } = options;

  function renderEntries(entries) {
    tableBody.innerHTML = '';

    if (!entries || entries.length === 0) {
      tableBody.appendChild(showEmptyTableRow(8, '📭', '暂无已处理条目'));
      return;
    }

    entries.forEach(function (it) {
      const tr = document.createElement('tr');

      // ID (Entry ID)
      const tdId = document.createElement('td');
      tdId.className = 'mono';
      tdId.style.fontSize = '12px';
      tdId.textContent = it.id || '-';
      tr.appendChild(tdId);

      // Canonical ID
      const tdCanonical = document.createElement('td');
      tdCanonical.className = 'mono';
      tdCanonical.style.fontSize = '12px';
      tdCanonical.textContent = it.canonical_id || '-';
      tr.appendChild(tdCanonical);

      // Trace ID (Webhook Trace ID)
      const tdTrace = document.createElement('td');
      tdTrace.className = 'mono';
      tdTrace.style.fontSize = '11px';
      tdTrace.textContent = it.trace_id || '-';
      tdTrace.title = it.trace_id ? 'Trace ID（处理链路）' : '';
      tr.appendChild(tdTrace);

      // Title
      const tdTitle = document.createElement('td');
      let titleText = it.title || '';
      if (titleText.length > 60) {
        titleText = titleText.substring(0, 60) + '...';
      }
      tdTitle.textContent = titleText;
      tdTitle.style.maxWidth = '300px';
      tdTitle.title = it.title || '';
      tr.appendChild(tdTitle);

      // Category
      const tdCategory = document.createElement('td');
      tdCategory.innerHTML = getCategoryBadge(it.ai_category);
      tr.appendChild(tdCategory);

      // Published At
      const tdTime = document.createElement('td');
      const datetime = it.published_at || it.datetime || it.created_at || '';
      tdTime.textContent = datetime ? new Date(datetime).toLocaleString('zh-CN') : '-';
      tr.appendChild(tdTime);

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
      const traceBtn = document.createElement('button');
      traceBtn.className = 'btn';
      traceBtn.textContent = 'Trace';
      traceBtn.style.padding = '2px 8px';
      traceBtn.style.fontSize = '11px';

      let isExpanded = false;
      let detailRow = null;

      traceBtn.addEventListener('click', async function () {
        if (isExpanded) {
          // 收起
          if (detailRow) {
            detailRow.remove();
            detailRow = null;
          }
          isExpanded = false;
          traceBtn.textContent = 'Trace';
          return;
        }

        // 展开
        if (!it.canonical_id) {
          alert('该条目缺少 canonical_id');
          return;
        }

        isExpanded = true;
        traceBtn.textContent = '收起';

        // 创建展开行
        detailRow = document.createElement('tr');
        const detailTd = document.createElement('td');
        detailTd.colSpan = 8;
        detailTd.style.padding = 'var(--space-md)';
        detailTd.style.background = '#f6f8fa';
        detailTd.innerHTML = '<div style="color: var(--text-muted);">加载中...</div>';
        detailRow.appendChild(detailTd);
        tr.parentNode.insertBefore(detailRow, tr.nextSibling);

        try {
          // 只用 canonical_id 调用 API，获取所有处理历史
          const data = await request('GET', API.canonicalTrace(it.canonical_id));

          if (data.status === 'not_found' || !data.stages || data.stages.length === 0) {
            detailTd.innerHTML = '<div style="color: var(--text-muted);">未找到处理记录</div>';
            return;
          }

          // 按 trace_id 分组 stages
          const traceGroups = groupByTraceId(data.stages);

          // 渲染处理历史列表
          renderTraceHistory(detailTd, traceGroups, it.canonical_id);

        } catch (e) {
          detailTd.innerHTML = `<div style="color: var(--error-text);">加载失败: ${e.message}</div>`;
        }
      });

      tdOp.appendChild(traceBtn);
      tr.appendChild(tdOp);

      tableBody.appendChild(tr);
    });
  }

  async function loadEntries() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    refreshBtn.disabled = true;

    const limitVal = parseInt((limitInput.value || '100').trim(), 10) || 100;
    const offsetVal = parseInt((offsetInput.value || '0').trim(), 10) || 0;

    const url = `${API.processedEntries}?limit=${encodeURIComponent(limitVal)}&offset=${encodeURIComponent(offsetVal)}`;

    try {
      const data = await request('GET', url);

      outputEl.textContent = prettyPrint({
        status: data.status,
        total: data.total,
        returned: (data.entries || []).length,
      });

      totalEl.textContent = String(data.total || 0);
      countEl.textContent = String((data.entries || []).length);

      if (data.total === 0) {
        rangeEl.textContent = '0-0';
      } else {
        const start = offsetVal + 1;
        const end = Math.min(offsetVal + limitVal, data.total);
        rangeEl.textContent = `${start}-${end}`;
      }

      renderEntries(data.entries || []);
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      refreshBtn.disabled = false;
    }
  }

  loadBtn.addEventListener('click', loadEntries);
  refreshBtn.addEventListener('click', loadEntries);

  return { loadEntries };
}

/**
 * 初始化处理历史模块
 * @param {Object} options - 配置选项
 */
export function initProcessHistory(options) {
  const {
    loadBtn,
    refreshBtn,
    outputEl,
    tableBody,
    limitInput,
    totalEl,
    countEl,
    onBatchClick,
    searchInput,
    searchBtn,
    searchClearBtn,
    searchStatusEl
  } = options;

  // 当前是否为搜索模式
  let isSearchMode = false;

  // 批次状态徽章渲染
  function getBatchStatusBadge(status) {
    const statusMap = {
      'success': { class: 'badge-success', text: '成功' },
      'partial': { class: 'badge-warning', text: '部分成功' },
      'error': { class: 'badge-error', text: '失败' },
      'pending': { class: 'badge-info', text: '进行中' }
    };
    const info = statusMap[status] || { class: 'badge-info', text: status };
    return `<span class="badge ${info.class}">${info.text}</span>`;
  }

  // 条目状态徽章
  function getEntryStatusBadge(status) {
    const statusMap = {
      'success': { class: 'badge-success', text: '成功' },
      'error': { class: 'badge-error', text: '失败' },
      'pending': { class: 'badge-info', text: '待处理' }
    };
    const info = statusMap[status] || { class: 'badge-info', text: status };
    return `<span class="badge ${info.class}" style="font-size: 10px;">${info.text}</span>`;
  }

  // 格式化持续时间
  function formatMs(ms) {
    if (ms === null || ms === undefined) return '-';
    if (ms < 1000) return Math.round(ms) + 'ms';
    return (ms / 1000).toFixed(2) + 's';
  }

  // 渲染批次历史列表
  function renderHistory(traces, showMatchedEntry = false) {
    tableBody.innerHTML = '';

    if (!traces || traces.length === 0) {
      tableBody.appendChild(showEmptyTableRow(6, '📭', '暂无处理历史'));
      return;
    }

    traces.forEach(function (trace) {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';

      // Trace ID
      const tdTraceId = document.createElement('td');
      tdTraceId.className = 'mono';
      tdTraceId.style.fontSize = '11px';
      tdTraceId.textContent = (trace.trace_id || '').substring(0, 16) + '...';
      tdTraceId.title = trace.trace_id || '';
      tr.appendChild(tdTraceId);

      // 批次状态
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getBatchStatusBadge(trace.status);
      tr.appendChild(tdStatus);

      // 条目统计
      const tdEntries = document.createElement('td');
      tdEntries.className = 'mono';
      tdEntries.innerHTML = `<span style="color:var(--success-text)">${trace.success_count || 0}</span> / <span style="color:var(--error-text)">${trace.error_count || 0}</span> / ${trace.total_entries || 0}`;
      tdEntries.title = '成功 / 失败 / 总数';
      tr.appendChild(tdEntries);

      // 持续时间
      const tdDuration = document.createElement('td');
      tdDuration.className = 'mono';
      tdDuration.textContent = formatMs(trace.duration_ms);
      tr.appendChild(tdDuration);

      // 开始时间
      const tdTime = document.createElement('td');
      tdTime.textContent = formatTime(trace.start_time);
      tr.appendChild(tdTime);

      // 操作
      const tdOp = document.createElement('td');

      // 搜索模式下显示匹配条目信息
      if (showMatchedEntry && trace.matched_entry) {
        const entryInfo = trace.matched_entry;
        const entryDiv = document.createElement('div');
        entryDiv.style.marginBottom = '4px';
        entryDiv.innerHTML = `
          <div style="font-size: 10px; color: var(--text-secondary);">
            Entry: ${entryInfo.entry_id || '-'}
            ${entryInfo.ai_category ? getCategoryBadge(entryInfo.ai_category) : ''}
            ${getEntryStatusBadge(entryInfo.status)}
          </div>
        `;
        tdOp.appendChild(entryDiv);
      }

      const viewBtn = document.createElement('button');
      viewBtn.className = 'btn';
      viewBtn.textContent = '查看批次';
      viewBtn.style.padding = '2px 8px';
      viewBtn.style.fontSize = '11px';
      viewBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (onBatchClick) {
          onBatchClick(trace.trace_id);
        }
      });
      tdOp.appendChild(viewBtn);
      tr.appendChild(tdOp);

      // 整行点击
      tr.addEventListener('click', function () {
        if (onBatchClick) {
          onBatchClick(trace.trace_id);
        }
      });

      tableBody.appendChild(tr);
    });
  }

  async function loadHistory() {
    outputEl.textContent = '';
    loadBtn.disabled = true;
    refreshBtn.disabled = true;
    isSearchMode = false;

    if (searchStatusEl) {
      searchStatusEl.textContent = '';
    }

    const limitVal = parseInt((limitInput.value || '20').trim(), 10) || 20;

    try {
      const data = await request('GET', `${API.processHistory}?limit=${encodeURIComponent(limitVal)}`);

      outputEl.textContent = prettyPrint({
        status: data.status,
        total: data.total,
        returned: (data.traces || []).length,
      });

      totalEl.textContent = String(data.total || 0);
      countEl.textContent = String((data.traces || []).length);

      renderHistory(data.traces || []);
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      loadBtn.disabled = false;
      refreshBtn.disabled = false;
    }
  }

  async function performSearch() {
    const query = (searchInput.value || '').trim();
    if (!query) {
      searchStatusEl.textContent = '请输入搜索关键词';
      return;
    }

    outputEl.textContent = '';
    searchBtn.disabled = true;
    isSearchMode = true;

    if (searchStatusEl) {
      searchStatusEl.textContent = '搜索中...';
    }

    try {
      const data = await searchProcessHistory(query);

      const queryTypeText = data.query_type === 'entry_id' ? 'Entry ID' : 'Canonical ID';
      searchStatusEl.textContent = `找到 ${data.total} 个批次 (${queryTypeText}: ${query})`;

      outputEl.textContent = prettyPrint({
        status: data.status,
        query: data.query,
        query_type: data.query_type,
        total: data.total,
        returned: (data.traces || []).length,
      });

      totalEl.textContent = String(data.total || 0);
      countEl.textContent = String((data.traces || []).length);

      renderHistory(data.traces || [], true);
    } catch (e) {
      searchStatusEl.textContent = '搜索失败: ' + e.message;
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      searchBtn.disabled = false;
    }
  }

  function clearSearch() {
    searchInput.value = '';
    if (searchStatusEl) {
      searchStatusEl.textContent = '';
    }
    loadHistory();
  }

  loadBtn.addEventListener('click', loadHistory);
  refreshBtn.addEventListener('click', loadHistory);

  if (searchBtn) {
    searchBtn.addEventListener('click', performSearch);
  }

  if (searchClearBtn) {
    searchClearBtn.addEventListener('click', clearSearch);
  }

  if (searchInput) {
    searchInput.addEventListener('keypress', function (e) {
      if (e.key === 'Enter') {
        performSearch();
      }
    });
  }

  return { loadHistory };
}

/**
 * 按 trace_id 分组 stages
 * @param {Array} stages - 阶段列表
 * @returns {Array} 分组后的批次列表
 */
function groupByTraceId(stages) {
  const groups = {};
  stages.forEach(function (stage) {
    const tid = stage.data?.trace_id || stage.trace_id || 'unknown';
    if (!groups[tid]) {
      groups[tid] = {
        trace_id: tid,
        stages: [],
        first_timestamp: stage.timestamp,
        last_timestamp: stage.timestamp,
        status: 'unknown'
      };
    }
    groups[tid].stages.push(stage);

    // 更新时间范围
    if (stage.timestamp < groups[tid].first_timestamp) {
      groups[tid].first_timestamp = stage.timestamp;
    }
    if (stage.timestamp > groups[tid].last_timestamp) {
      groups[tid].last_timestamp = stage.timestamp;
    }

    // 获取最终状态
    if (stage.stage === 'process' && stage.action === 'complete') {
      groups[tid].status = stage.status || 'success';
      groups[tid].ai_category = stage.data?.ai_category;
      groups[tid].duration_ms = stage.duration_ms;
    }
  });
  return Object.values(groups);
}

/**
 * 渲染处理历史列表
 * @param {HTMLElement} container - 容器元素
 * @param {Array} traceGroups - 分组后的批次列表
 * @param {string} canonicalId - 条目 canonical_id
 */
function renderTraceHistory(container, traceGroups, canonicalId) {
  container.innerHTML = '';

  const titleDiv = document.createElement('div');
  titleDiv.style.cssText = 'font-size: 13px; font-weight: 600; margin-bottom: var(--space-md); color: var(--text-primary);';
  titleDiv.textContent = `处理历史 (${traceGroups.length} 个批次)`;
  container.appendChild(titleDiv);

  // 按时间倒序排列
  traceGroups.sort((a, b) => b.first_timestamp.localeCompare(a.first_timestamp));

  traceGroups.forEach(function (group) {
    const card = document.createElement('div');
    card.style.cssText = `
      background: var(--bg-card);
      border: 1px solid var(--border-secondary);
      border-radius: var(--radius-md);
      padding: var(--space-md);
      margin-bottom: var(--space-sm);
      cursor: pointer;
      transition: border-color 0.2s;
    `;

    const statusBadgeClass = getStatusBadgeClass(group.status);
    const statusText = group.status === 'success' ? '成功' :
                       group.status === 'error' ? '失败' : group.status;

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: var(--space-sm);">
          <span class="badge ${statusBadgeClass}">${statusText}</span>
          <span style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">
            ${group.trace_id ? group.trace_id.substring(0, 16) + '...' : '-'}
          </span>
          ${group.ai_category ? `<span class="badge badge-info">${group.ai_category}</span>` : ''}
        </div>
        <div style="display: flex; align-items: center; gap: var(--space-md); font-size: 12px; color: var(--text-secondary);">
          <span>${formatTime(group.first_timestamp)}</span>
          ${group.duration_ms ? `<span>${formatDuration(group.duration_ms)}</span>` : ''}
          <span>${group.stages.length} 阶段</span>
        </div>
      </div>
      <div class="stages-container" style="display: none; margin-top: var(--space-md); border-top: 1px solid var(--border-secondary); padding-top: var(--space-md);"></div>
    `;

    // 点击展开详细阶段
    card.addEventListener('click', function () {
      const stagesContainer = card.querySelector('.stages-container');
      if (stagesContainer.style.display === 'none') {
        stagesContainer.innerHTML = '';
        renderTimeline(group.stages, stagesContainer);
        stagesContainer.style.display = 'block';
        card.style.borderColor = 'var(--primary)';
      } else {
        stagesContainer.style.display = 'none';
        card.style.borderColor = 'var(--border-secondary)';
      }
    });

    container.appendChild(card);
  });
}
