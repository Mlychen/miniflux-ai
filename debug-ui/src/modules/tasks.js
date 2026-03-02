/**
 * 任务管理模块
 *
 * 语义说明：
 * - trace_id: 处理链路 ID（用于聚合一次处理请求产生的所有任务）
 * - canonical_id: 条目逻辑唯一标识
 */

import {
  request,
  prettyPrint,
  parsePositiveInt,
  formatUnixSeconds,
  escapeHtml,
  API
} from '../api/index.js';
import { getTaskStatusBadge, showEmptyTableRow } from './ui.js';

/**
 * 初始化任务管理模块
 * @param {Object} options - 配置选项
 */
export function initTaskManager(options) {
  const {
    // 分组相关
    groupsLoadBtn,
    statusFilter,
    errorFilter,
    groupLimit,
    groupsBody,
    groupsTotal,
    groupsCount,
    currentGroupEl,

    // 任务样本相关
    samplesLoadBtn,
    sampleLimit,
    sampleOffset,
    sampleIncludePayload,
    samplesBody,
    samplesTotal,
    samplesCount,
    detailIdInput,
    detailLoadBtn,

    // 操作按钮
    filterRequeueBtn,
    groupRequeueBtn,

    // 输出
    outputEl
  } = options;

  let selectedFailureGroup = null;

  function updateCurrentGroupDisplay() {
    if (!selectedFailureGroup) {
      currentGroupEl.textContent = '(none)';
      return;
    }
    currentGroupEl.textContent = `${selectedFailureGroup.status}/${selectedFailureGroup.error_key}`;
  }

  function buildFailureGroupQuery(limitVal) {
    const params = new URLSearchParams();
    params.set('limit', String(limitVal));

    const status = (statusFilter.value || '').trim();
    if (status) {
      params.set('status', status);
    }

    const error = (errorFilter.value || '').trim();
    if (error) {
      params.set('error', error);
    }
    return params;
  }

  function renderFailureGroups(groups) {
    groupsBody.innerHTML = '';
    if (!groups || groups.length === 0) {
      groupsBody.appendChild(showEmptyTableRow(7, '✅', '暂无失败分组'));
      return;
    }

    groups.forEach(function (group) {
      const tr = document.createElement('tr');

      // Status
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getTaskStatusBadge(group.status);
      tr.appendChild(tdStatus);

      // Error Key
      const tdErrorKey = document.createElement('td');
      tdErrorKey.className = 'mono';
      tdErrorKey.style.fontSize = '11px';
      tdErrorKey.textContent = group.error_key || '(empty)';
      tr.appendChild(tdErrorKey);

      // Error
      const tdError = document.createElement('td');
      tdError.textContent = group.error || '-';
      tdError.title = group.error || '';
      tdError.style.maxWidth = '360px';
      tdError.style.wordBreak = 'break-word';
      tr.appendChild(tdError);

      // Count
      const tdCount = document.createElement('td');
      tdCount.className = 'mono';
      tdCount.textContent = String(group.count || 0);
      tr.appendChild(tdCount);

      // Latest Updated
      const tdUpdated = document.createElement('td');
      tdUpdated.textContent = formatUnixSeconds(group.latest_updated_at);
      tr.appendChild(tdUpdated);

      // Oldest Created
      const tdCreated = document.createElement('td');
      tdCreated.textContent = formatUnixSeconds(group.oldest_created_at);
      tr.appendChild(tdCreated);

      // Operations
      const tdOps = document.createElement('td');

      const viewBtn = document.createElement('button');
      viewBtn.className = 'btn';
      viewBtn.textContent = '查看任务';
      viewBtn.addEventListener('click', function () {
        selectedFailureGroup = {
          status: String(group.status || ''),
          error_key: String(group.error_key || '(empty)'),
        };
        updateCurrentGroupDisplay();
        sampleOffset.value = '0';
        loadFailureGroupTasks();
      });

      const requeueBtn = document.createElement('button');
      requeueBtn.className = 'btn btn-danger';
      requeueBtn.textContent = '重入队该组';
      requeueBtn.style.marginLeft = '4px';
      requeueBtn.addEventListener('click', function () {
        requeueFailureGroup({
          status: String(group.status || ''),
          error_key: String(group.error_key || '(empty)'),
        });
      });

      tdOps.appendChild(viewBtn);
      tdOps.appendChild(requeueBtn);
      tr.appendChild(tdOps);

      groupsBody.appendChild(tr);
    });
  }

  function renderFailureTasks(tasks) {
    samplesBody.innerHTML = '';
    if (!tasks || tasks.length === 0) {
      samplesBody.appendChild(showEmptyTableRow(7, '📭', '该分组下暂无任务'));
      return;
    }

    tasks.forEach(function (task) {
      const tr = document.createElement('tr');

      // ID
      const tdId = document.createElement('td');
      tdId.className = 'mono';
      tdId.textContent = String(task.id || '');
      tr.appendChild(tdId);

      // Status
      const tdStatus = document.createElement('td');
      tdStatus.innerHTML = getTaskStatusBadge(task.status);
      tr.appendChild(tdStatus);

      // Attempts
      const tdAttempts = document.createElement('td');
      tdAttempts.className = 'mono';
      tdAttempts.textContent = `${task.attempts || 0}/${task.max_attempts || '?'}`;
      tr.appendChild(tdAttempts);

      // Error Key
      const tdErrorKey = document.createElement('td');
      tdErrorKey.className = 'mono';
      tdErrorKey.style.fontSize = '11px';
      tdErrorKey.textContent = task.error_key || '(empty)';
      tr.appendChild(tdErrorKey);

      // Trace ID (Webhook Trace ID)
      const tdTrace = document.createElement('td');
      tdTrace.className = 'mono';
      tdTrace.style.fontSize = '11px';
      tdTrace.textContent = task.trace_id || '-';
      tdTrace.title = task.trace_id ? 'Trace ID（处理链路）' : '';
      tr.appendChild(tdTrace);

      // Updated
      const tdUpdated = document.createElement('td');
      tdUpdated.textContent = formatUnixSeconds(task.updated_at);
      tr.appendChild(tdUpdated);

      // Operations
      const tdOps = document.createElement('td');

      const requeueBtn = document.createElement('button');
      requeueBtn.className = 'btn';
      requeueBtn.textContent = '重入队任务';
      requeueBtn.addEventListener('click', function () {
        requeueSingleTask(task.id, requeueBtn);
      });

      const detailBtn = document.createElement('button');
      detailBtn.className = 'btn';
      detailBtn.textContent = '详情';
      detailBtn.style.marginLeft = '4px';
      detailBtn.addEventListener('click', function () {
        detailIdInput.value = String(task.id || '');
        loadTaskDetail();
      });

      tdOps.appendChild(requeueBtn);
      tdOps.appendChild(detailBtn);
      tr.appendChild(tdOps);

      samplesBody.appendChild(tr);
    });
  }

  async function loadTaskFailureGroups() {
    outputEl.textContent = '';
    groupsLoadBtn.disabled = true;
    groupsLoadBtn.textContent = '加载中...';

    const limitVal = parsePositiveInt(groupLimit.value, 50);
    const previousSelection = selectedFailureGroup
      ? `${selectedFailureGroup.status}|${selectedFailureGroup.error_key}`
      : '';
    const params = buildFailureGroupQuery(limitVal);
    const url = `${API.failureGroups}?${params.toString()}`;

    try {
      const data = await request('GET', url);
      const groups = data.groups || [];

      if (previousSelection) {
        const matched = groups.find(function (item) {
          return `${item.status}|${item.error_key}` === previousSelection;
        });
        selectedFailureGroup = matched
          ? { status: String(matched.status), error_key: String(matched.error_key) }
          : null;
      } else {
        selectedFailureGroup = null;
      }

      updateCurrentGroupDisplay();
      groupsTotal.textContent = String(data.total || 0);
      groupsCount.textContent = String(groups.length);
      renderFailureGroups(groups);

      outputEl.textContent = prettyPrint({
        status: data.status,
        endpoint: 'failure-groups',
        total: data.total,
        returned: groups.length,
        status_filter: data.status_filter,
        error_key_filter: data.error_key_filter,
      });
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      groupsLoadBtn.disabled = false;
      groupsLoadBtn.textContent = '加载分组';
    }
  }

  async function loadFailureGroupTasks() {
    outputEl.textContent = '';
    samplesLoadBtn.disabled = true;
    samplesLoadBtn.textContent = '加载中...';

    const limitVal = parsePositiveInt(sampleLimit.value, 20);
    const offsetVal = parsePositiveInt(sampleOffset.value, 0);
    const params = new URLSearchParams();
    params.set('limit', String(limitVal));
    params.set('offset', String(offsetVal));
    params.set('include_payload', sampleIncludePayload.checked ? 'true' : 'false');

    if (selectedFailureGroup) {
      params.set('status', selectedFailureGroup.status);
      params.set('error_key', selectedFailureGroup.error_key);
    } else {
      const status = (statusFilter.value || '').trim();
      if (status) {
        params.set('status', status);
      }
      const error = (errorFilter.value || '').trim();
      if (error) {
        params.set('error', error);
      }
    }

    const url = `${API.failureGroupTasks}?${params.toString()}`;

    try {
      const data = await request('GET', url);
      samplesTotal.textContent = String(data.total || 0);
      samplesCount.textContent = String((data.tasks || []).length);
      renderFailureTasks(data.tasks || []);

      outputEl.textContent = prettyPrint({
        status: data.status,
        endpoint: 'failure-groups/tasks',
        total: data.total,
        returned: (data.tasks || []).length,
        status_filter: data.status_filter,
        error_key_filter: data.error_key_filter,
      });
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      samplesLoadBtn.disabled = false;
      samplesLoadBtn.textContent = '加载任务样本';
    }
  }

  async function requeueFailureGroup(group) {
    outputEl.textContent = '';
    const limitVal = parsePositiveInt(groupLimit.value, 100);
    groupRequeueBtn.disabled = true;
    groupRequeueBtn.textContent = '重入队中...';

    try {
      const data = await request('POST', API.requeueGroup, {
        status: group.status,
        error_key: group.error_key,
        limit: limitVal,
      });

      outputEl.textContent = prettyPrint(data);
      selectedFailureGroup = { status: group.status, error_key: group.error_key };
      updateCurrentGroupDisplay();
      loadTaskFailureGroups();
      loadFailureGroupTasks();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      groupRequeueBtn.disabled = false;
      groupRequeueBtn.textContent = '重入队当前分组';
    }
  }

  async function requeueByCurrentFilters() {
    outputEl.textContent = '';
    const limitVal = parsePositiveInt(groupLimit.value, 100);
    const payload = { limit: limitVal };

    const status = (statusFilter.value || '').trim();
    if (status) {
      payload.status = status;
    }
    const error = (errorFilter.value || '').trim();
    if (error) {
      payload.error = error;
    }

    filterRequeueBtn.disabled = true;
    filterRequeueBtn.textContent = '重入队中...';

    try {
      const data = await request('POST', API.requeueGroup, payload);
      outputEl.textContent = prettyPrint({
        mode: 'filter-requeue',
        status_filter: status || null,
        error_filter: error || null,
        ...data,
      });
      selectedFailureGroup = null;
      updateCurrentGroupDisplay();
      loadTaskFailureGroups();
      loadFailureGroupTasks();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      filterRequeueBtn.disabled = false;
      filterRequeueBtn.textContent = '按筛选重入队';
    }
  }

  async function loadTaskDetail() {
    outputEl.textContent = '';
    const rawTaskId = (detailIdInput.value || '').trim();
    if (!rawTaskId || !/^\d+$/.test(rawTaskId)) {
      outputEl.textContent = '请输入合法 task_id（正整数）';
      return;
    }

    detailLoadBtn.disabled = true;
    detailLoadBtn.textContent = '查询中...';

    try {
      const data = await request('GET', API.taskDetail(rawTaskId));
      outputEl.textContent = prettyPrint(data);

      const task = data.task || {};
      if (task.status === 'retryable' || task.status === 'dead') {
        selectedFailureGroup = {
          status: String(task.status),
          error_key: String(task.error_key || '(empty)'),
        };
        updateCurrentGroupDisplay();
      }
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      detailLoadBtn.disabled = false;
      detailLoadBtn.textContent = '查看任务详情';
    }
  }

  async function requeueSingleTask(taskId, buttonEl) {
    outputEl.textContent = '';
    buttonEl.disabled = true;
    buttonEl.textContent = '重入队中...';

    try {
      const data = await request('POST', API.requeueTask(taskId), {});
      outputEl.textContent = prettyPrint(data);
      loadTaskFailureGroups();
      loadFailureGroupTasks();
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      buttonEl.disabled = false;
      buttonEl.textContent = '重入队任务';
    }
  }

  // 绑定事件
  groupsLoadBtn.addEventListener('click', loadTaskFailureGroups);
  samplesLoadBtn.addEventListener('click', loadFailureGroupTasks);
  filterRequeueBtn.addEventListener('click', requeueByCurrentFilters);
  detailLoadBtn.addEventListener('click', loadTaskDetail);

  groupRequeueBtn.addEventListener('click', function () {
    if (!selectedFailureGroup) {
      outputEl.textContent = '请先在分组表中选择一个分组。';
      return;
    }
    requeueFailureGroup(selectedFailureGroup);
  });

  return {
    loadTaskFailureGroups,
    loadFailureGroupTasks,
    loadTaskDetail
  };
}
