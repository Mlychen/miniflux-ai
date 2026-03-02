/**
 * 处理追踪模块
 *
 * 语义说明：
 * - trace_id: 处理链路 ID（来自 manual-process 等入口）
 * - entry_id: Miniflux 条目 ID
 * - canonical_id: 条目逻辑唯一标识
 */

import {
  request,
  prettyPrint,
  formatTime,
  formatDuration,
  API
} from '../api/index.js';
import { getStatusBadgeClass } from './ui.js';

// 阶段标签映射
const STAGE_LABELS = {
  'process': '处理',
  'dedup': '去重检查',
  'preprocess': '预处理',
  'canonical_id': '生成 Canonical ID',
  'agent_process': 'Agent 处理',
  'save_result': '保存结果',
  'update_miniflux': '更新 Miniflux',
};

// 动作标签映射
const ACTION_LABELS = {
  'start': '开始',
  'complete': '完成',
  'error': '错误',
  'skipped': '跳过',
  'filtered': '已过滤',
  'passed': '通过',
  'generated': '已生成',
  'llm_call_start': 'LLM 调用开始',
  'llm_call_complete': 'LLM 调用完成',
  'llm_call_error': 'LLM 调用错误',
  'parse_error': '解析错误',
  'saving': '保存中',
};

// 批次状态映射
const BATCH_STATUS_LABELS = {
  'success': { class: 'badge-success', text: '全部成功' },
  'partial': { class: 'badge-warning', text: '部分成功' },
  'error': { class: 'badge-error', text: '全部失败' },
  'pending': { class: 'badge-info', text: '处理中' }
};

/**
 * 渲染时间线
 * @param {Array} stages - 阶段数据数组
 * @param {HTMLElement} container - 容器元素
 */
export function renderTimeline(stages, container) {
  if (!stages || stages.length === 0) {
    container.innerHTML = '<div class="empty-state"><div class="empty-state-text">暂无处理阶段</div></div>';
    return;
  }

  container.innerHTML = '';

  stages.forEach(function (stage) {
    const div = document.createElement('div');
    div.className = 'timeline-item ' + (stage.status || 'info');

    const stageLabel = STAGE_LABELS[stage.stage] || stage.stage;
    const actionLabel = ACTION_LABELS[stage.action] || stage.action;
    const statusText = stage.status === 'success' ? '✓ 完成' :
                       stage.status === 'error' ? '✗ 错误' : stage.status;

    let detailsHtml = '';
    if (stage.data) {
      const data = stage.data;
      const details = [];

      if (data.agent) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">Agent:</span> <span class="timeline-detail-value">' + data.agent + '</span></span>');
      if (data.response_length) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">响应长度:</span> <span class="timeline-detail-value">' + data.response_length + '</span></span>');
      if (data.canonical_id) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">Canonical ID:</span> <span class="timeline-detail-value mono" style="font-size:10px;">' + data.canonical_id.substring(0, 16) + '...</span></span>');
      if (data.ai_category) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">类别:</span> <span class="timeline-detail-value">' + data.ai_category + '</span></span>');
      if (data.agents_processed) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">Agents:</span> <span class="timeline-detail-value">' + data.agents_processed + '</span></span>');
      if (data.content_length) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">内容长度:</span> <span class="timeline-detail-value">' + data.content_length + '</span></span>');
      if (data.error) details.push('<span class="timeline-detail-item" style="color:var(--error-text);"><span class="timeline-detail-label">错误:</span> <span class="timeline-detail-value">' + data.error + '</span></span>');
      if (data.reason) details.push('<span class="timeline-detail-item"><span class="timeline-detail-label">原因:</span> <span class="timeline-detail-value">' + data.reason + '</span></span>');

      if (details.length > 0) {
        detailsHtml = '<div class="timeline-detail-row" style="margin-top:var(--space-xs);">' + details.join('') + '</div>';
      }

      // LLM 详情展开
      if (data.prompt_template || data.input_text || data.raw_response) {
        const expandId = 'expand-' + Math.random().toString(36).substr(2, 9);
        detailsHtml += `
          <div style="margin-top: var(--space-sm);">
            <button class="btn" style="padding: 2px 8px; font-size: 11px;" onclick="document.getElementById('${expandId}').style.display = document.getElementById('${expandId}').style.display === 'none' ? 'block' : 'none'">
              查看原始请求/回应
            </button>
            <div id="${expandId}" style="display: none; margin-top: var(--space-sm); background: var(--bg-primary); padding: var(--space-sm); border-radius: var(--radius-sm); border: 1px solid var(--border-secondary);">
              ${data.prompt_template ? `<div style="margin-bottom:8px;"><div style="color:var(--text-muted);font-size:10px;">PROMPT TEMPLATE</div><pre style="margin:4px 0;font-size:11px;white-space:pre-wrap;color:var(--code-text);">${data.prompt_template.replace(/</g, '&lt;')}</pre></div>` : ''}
              ${data.input_text ? `<div style="margin-bottom:8px;"><div style="color:var(--text-muted);font-size:10px;">INPUT TEXT</div><pre style="margin:4px 0;font-size:11px;white-space:pre-wrap;color:var(--code-text);">${data.input_text.replace(/</g, '&lt;')}</pre></div>` : ''}
              ${data.raw_response ? `<div><div style="color:var(--text-muted);font-size:10px;">RAW RESPONSE</div><pre style="margin:4px 0;font-size:11px;white-space:pre-wrap;color:var(--success-text);">${(typeof data.raw_response === 'string' ? data.raw_response : JSON.stringify(data.raw_response, null, 2)).replace(/</g, '&lt;')}</pre></div>` : ''}
            </div>
          </div>
        `;
      }
    }

    div.innerHTML = `
      <div class="timeline-content">
        <div class="timeline-header">
          <span class="timeline-stage">${stageLabel} - ${actionLabel}</span>
          <span class="timeline-time">${formatTime(stage.timestamp)}</span>
        </div>
        <div class="timeline-details">
          <span class="badge ${getStatusBadgeClass(stage.status)}">${statusText}</span>
          ${stage.duration_ms ? '<span class="timeline-detail-item" style="margin-left:var(--space-sm);"><span class="timeline-detail-label">耗时:</span> <span class="timeline-detail-value">' + formatDuration(stage.duration_ms) + '</span></span>' : ''}
          ${detailsHtml}
        </div>
      </div>
    `;

    container.appendChild(div);
  });
}

/**
 * 初始化处理追踪模块
 * @param {Object} options - 配置选项
 */
export function initProcessTrace(options) {
  const {
    traceInput,
    queryBtn,
    clearBtn,
    backBtn,
    outputEl,
    summaryEl,
    timelineEl,
    listEl,
    listBodyEl,
    statusEl,
    durationEl,
    stagesCountEl,
    canonicalIdEl,
    categoryEl,
    onLoadTrace
  } = options;

  let lastEntryIdForList = null;
  let lastTraceIdForBatch = null;

  // 渲染批次详情视图
  function renderBatchView(data) {
    const summary = data.summary || {};
    const entries = data.entries || [];

    // 批次状态徽章
    const batchStatusInfo = BATCH_STATUS_LABELS[summary.status] || { class: 'badge-info', text: summary.status };

    // 更新摘要区域
    statusEl.innerHTML = `<span class="badge ${batchStatusInfo.class}">${batchStatusInfo.text}</span>`;
    durationEl.textContent = formatDuration(summary.total_duration_ms);
    stagesCountEl.textContent = `${summary.success_count || 0}/${summary.total_entries || 0}`;
    canonicalIdEl.textContent = data.trace_id ? data.trace_id.substring(0, 16) + '...' : '-';
    canonicalIdEl.title = data.trace_id || '';
    categoryEl.textContent = `${summary.success_count || 0} 成功 / ${summary.error_count || 0} 失败`;
    summaryEl.style.display = 'block';

    // 渲染条目列表
    timelineEl.innerHTML = '';

    if (entries.length === 0) {
      timelineEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">批次内无条目</div></div>';
      timelineEl.style.display = 'block';
      return;
    }

    // 创建条目卡片列表
    const entriesContainer = document.createElement('div');
    entriesContainer.className = 'batch-entries-list';

    entries.forEach(function (entry, idx) {
      const card = document.createElement('div');
      card.className = 'batch-entry-card';
      card.style.cssText = `
        background: var(--bg-primary);
        border: 1px solid var(--border-secondary);
        border-radius: var(--radius-md);
        padding: var(--space-md);
        margin-bottom: var(--space-sm);
        cursor: pointer;
        transition: border-color 0.2s;
      `;

      const statusBadgeClass = getStatusBadgeClass(entry.status);
      const statusText = entry.status === 'success' ? '✓ 成功' :
                         entry.status === 'error' ? '✗ 失败' : entry.status;

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-xs);">
          <div style="display: flex; align-items: center; gap: var(--space-sm);">
            <span class="badge ${statusBadgeClass}">${statusText}</span>
            <span style="color: var(--text-muted); font-size: 11px;">
              ${entry.ai_category || '未分类'}
            </span>
          </div>
          <span style="color: var(--text-muted); font-size: 11px;">
            ${formatDuration(entry.duration_ms)} · ${entry.stages_count || 0} 阶段
          </span>
        </div>
        <div style="font-family: monospace; font-size: 11px; color: var(--text-secondary);">
          canonical_id: ${entry.canonical_id ? (entry.canonical_id.substring(0, 24) + '...') : '-'}
          ${entry.entry_id ? `<span style="margin-left: var(--space-sm);">entry_id: ${entry.entry_id}</span>` : ''}
        </div>
        <div class="entry-stages-container" style="display: none; margin-top: var(--space-md); border-top: 1px solid var(--border-secondary); padding-top: var(--space-md);"></div>
      `;

      // 点击展开/收起详细阶段
      card.addEventListener('click', async function () {
        const stagesContainer = card.querySelector('.entry-stages-container');
        if (stagesContainer.style.display === 'none') {
          // 展开 - 加载详细阶段
          if (entry.canonical_id) {
            stagesContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 11px;">加载中...</div>';
            stagesContainer.style.display = 'block';

            try {
              const detailData = await request('GET', API.canonicalTrace(entry.canonical_id, data.trace_id));
              if (detailData.stages && detailData.stages.length > 0) {
                stagesContainer.innerHTML = '';
                renderTimeline(detailData.stages, stagesContainer);
              } else {
                stagesContainer.innerHTML = '<div style="color: var(--text-muted);">暂无处理阶段</div>';
              }
            } catch (e) {
              stagesContainer.innerHTML = `<div style="color: var(--error-text);">加载失败: ${e.message}</div>`;
            }
          } else {
            stagesContainer.innerHTML = '<div style="color: var(--text-muted);">无 canonical_id</div>';
            stagesContainer.style.display = 'block';
          }
          card.style.borderColor = 'var(--primary)';
        } else {
          // 收起
          stagesContainer.style.display = 'none';
          card.style.borderColor = 'var(--border-secondary)';
        }
      });

      entriesContainer.appendChild(card);
    });

    timelineEl.appendChild(entriesContainer);
    timelineEl.style.display = 'block';
  }

  async function loadTrace() {
    const id = (traceInput.value || '').trim();
    outputEl.textContent = '';
    summaryEl.style.display = 'none';
    timelineEl.style.display = 'none';
    listEl.style.display = 'none';
    backBtn.style.display = 'none';

    if (!id) {
      outputEl.textContent = '请输入 Trace ID 或 Entry ID';
      return;
    }

    queryBtn.disabled = true;
    queryBtn.textContent = '查询中...';

    try {
      const data = await request('GET', API.processTrace(id));

      if (data.status === 'not_found') {
        outputEl.textContent = '未找到该 ID 的处理记录: ' + id;
        if (lastEntryIdForList && id !== lastEntryIdForList) {
          backBtn.style.display = 'inline-flex';
        }
        return;
      }

      // 列表模式：按 Entry ID 查询返回多个 trace
      if (data.type === 'list') {
        lastEntryIdForList = id;
        listBodyEl.innerHTML = '';

        (data.traces || []).forEach(t => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td class="mono" style="font-size:11px;">${t.trace_id}</td>
            <td><span class="badge ${getStatusBadgeClass(t.status)}">${t.status}</span></td>
            <td>${formatTime(t.start_time)}</td>
            <td><button class="btn" style="padding: 2px 8px; font-size: 11px;">查看</button></td>
          `;
          tr.querySelector('button').onclick = () => {
            traceInput.value = t.trace_id;
            loadTrace();
          };
          listBodyEl.appendChild(tr);
        });

        listEl.style.display = 'block';
        outputEl.textContent = `找到 ${data.traces.length} 条处理记录，请选择一条查看详情。`;
        return;
      }

      // 批次模式：按 Trace ID 查询返回批次内所有 canonical_id
      if (data.type === 'batch') {
        lastTraceIdForBatch = data.trace_id;
        outputEl.textContent = prettyPrint({
          status: data.status,
          trace_id: data.trace_id,
          type: 'batch',
          total_entries: data.summary?.total_entries,
          success_count: data.summary?.success_count,
          error_count: data.summary?.error_count,
        });

        renderBatchView(data);

        // 回调
        if (onLoadTrace) {
          onLoadTrace(data);
        }
        return;
      }

      // 详情模式（旧版兼容，单个条目的详细 stages）
      outputEl.textContent = prettyPrint({
        status: data.status,
        entry_id: data.entry_id,
        trace_id: data.trace_id,
        stages_count: (data.stages || []).length,
      });

      // 显示摘要
      if (data.summary) {
        const summary = data.summary;
        statusEl.innerHTML = `<span class="badge ${getStatusBadgeClass(summary.status)}">${summary.status === 'success' ? '成功' : summary.status === 'error' ? '失败' : summary.status}</span>`;
        durationEl.textContent = formatDuration(summary.total_duration_ms);
        stagesCountEl.textContent = summary.stages_count || 0;
        canonicalIdEl.textContent = summary.canonical_id || '-';
        categoryEl.textContent = summary.ai_category || '-';
        summaryEl.style.display = 'block';
      }

      // 显示时间线
      if (data.stages && data.stages.length > 0) {
        renderTimeline(data.stages, timelineEl);
        timelineEl.style.display = 'block';
      }

      // 显示返回按钮
      if (lastEntryIdForList && id !== lastEntryIdForList) {
        backBtn.style.display = 'inline-flex';
      }

      // 回调
      if (onLoadTrace) {
        onLoadTrace(data);
      }
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
      if (lastEntryIdForList && id !== lastEntryIdForList) {
        backBtn.style.display = 'inline-flex';
      }
    } finally {
      queryBtn.disabled = false;
      queryBtn.textContent = '查询';
    }
  }

  queryBtn.addEventListener('click', loadTrace);

  backBtn.addEventListener('click', function () {
    if (lastEntryIdForList) {
      traceInput.value = lastEntryIdForList;
      loadTrace();
    }
  });

  clearBtn.addEventListener('click', function () {
    traceInput.value = '';
    outputEl.textContent = '';
    summaryEl.style.display = 'none';
    timelineEl.style.display = 'none';
    listEl.style.display = 'none';
    backBtn.style.display = 'none';
    lastEntryIdForList = null;
    lastTraceIdForBatch = null;
  });

  return { loadTrace };
}

/**
 * 加载指定 trace_id 的批次详情
 * @param {string} traceId - Trace ID
 */
export async function loadBatchByTraceId(traceId, options) {
  const {
    outputEl,
    summaryEl,
    timelineEl,
    statusEl,
    durationEl,
    stagesCountEl,
    canonicalIdEl,
    categoryEl
  } = options;

  outputEl.textContent = '';
  summaryEl.style.display = 'none';
  timelineEl.style.display = 'none';

  try {
    const data = await request('GET', API.processTrace(traceId));

    if (data.status === 'not_found') {
      outputEl.textContent = '未找到该 Trace ID 的处理记录: ' + traceId;
      return;
    }

    if (data.type === 'batch') {
      outputEl.textContent = prettyPrint({
        status: data.status,
        trace_id: data.trace_id,
        type: 'batch',
        total_entries: data.summary?.total_entries,
        success_count: data.summary?.success_count,
        error_count: data.summary?.error_count,
      });

      const summary = data.summary || {};
      const batchStatusInfo = BATCH_STATUS_LABELS[summary.status] || { class: 'badge-info', text: summary.status };

      statusEl.innerHTML = `<span class="badge ${batchStatusInfo.class}">${batchStatusInfo.text}</span>`;
      durationEl.textContent = formatDuration(summary.total_duration_ms);
      stagesCountEl.textContent = `${summary.success_count || 0}/${summary.total_entries || 0}`;
      canonicalIdEl.textContent = data.trace_id ? data.trace_id.substring(0, 16) + '...' : '-';
      canonicalIdEl.title = data.trace_id || '';
      categoryEl.textContent = `${summary.success_count || 0} 成功 / ${summary.error_count || 0} 失败`;
      summaryEl.style.display = 'block';

      // 渲染条目列表
      const entries = data.entries || [];
      timelineEl.innerHTML = '';

      if (entries.length === 0) {
        timelineEl.innerHTML = '<div class="empty-state"><div class="empty-state-text">批次内无条目</div></div>';
        timelineEl.style.display = 'block';
        return;
      }

      const entriesContainer = document.createElement('div');
      entriesContainer.className = 'batch-entries-list';

      entries.forEach(function (entry) {
        const card = document.createElement('div');
        card.className = 'batch-entry-card';
        card.style.cssText = `
          background: var(--bg-primary);
          border: 1px solid var(--border-secondary);
          border-radius: var(--radius-md);
          padding: var(--space-md);
          margin-bottom: var(--space-sm);
          cursor: pointer;
          transition: border-color 0.2s;
        `;

        const statusBadgeClass = getStatusBadgeClass(entry.status);
        const statusText = entry.status === 'success' ? '✓ 成功' :
                           entry.status === 'error' ? '✗ 失败' : entry.status;

        card.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-xs);">
            <div style="display: flex; align-items: center; gap: var(--space-sm);">
              <span class="badge ${statusBadgeClass}">${statusText}</span>
              <span style="color: var(--text-muted); font-size: 11px;">
                ${entry.ai_category || '未分类'}
              </span>
            </div>
            <span style="color: var(--text-muted); font-size: 11px;">
              ${formatDuration(entry.duration_ms)} · ${entry.stages_count || 0} 阶段
            </span>
          </div>
          <div style="font-family: monospace; font-size: 11px; color: var(--text-secondary);">
            canonical_id: ${entry.canonical_id ? (entry.canonical_id.substring(0, 24) + '...') : '-'}
            ${entry.entry_id ? `<span style="margin-left: var(--space-sm);">entry_id: ${entry.entry_id}</span>` : ''}
          </div>
          <div class="entry-stages-container" style="display: none; margin-top: var(--space-md); border-top: 1px solid var(--border-secondary); padding-top: var(--space-md);"></div>
        `;

        // 点击展开详细阶段
        card.addEventListener('click', async function () {
          const stagesContainer = card.querySelector('.entry-stages-container');
          if (stagesContainer.style.display === 'none') {
            if (entry.canonical_id) {
              stagesContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 11px;">加载中...</div>';
              stagesContainer.style.display = 'block';

              try {
                const detailData = await request('GET', API.canonicalTrace(entry.canonical_id, data.trace_id));
                if (detailData.stages && detailData.stages.length > 0) {
                  stagesContainer.innerHTML = '';
                  renderTimeline(detailData.stages, stagesContainer);
                } else {
                  stagesContainer.innerHTML = '<div style="color: var(--text-muted);">暂无处理阶段</div>';
                }
              } catch (e) {
                stagesContainer.innerHTML = `<div style="color: var(--error-text);">加载失败: ${e.message}</div>`;
              }
            } else {
              stagesContainer.innerHTML = '<div style="color: var(--text-muted);">无 canonical_id</div>';
              stagesContainer.style.display = 'block';
            }
            card.style.borderColor = 'var(--primary)';
          } else {
            stagesContainer.style.display = 'none';
            card.style.borderColor = 'var(--border-secondary)';
          }
        });

        entriesContainer.appendChild(card);
      });

      timelineEl.appendChild(entriesContainer);
      timelineEl.style.display = 'block';
    }
  } catch (e) {
    outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
  }
}
