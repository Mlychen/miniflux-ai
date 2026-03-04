/**
 * miniflux-ai Debug Console - 主入口
 *
 * 语义说明：
 * - trace_id: 处理链路 ID，用于聚合一次处理请求产生的所有任务和日志
 * - canonical_id: 条目逻辑唯一标识（按 URL+title 生成）
 * - entry_id: Miniflux 原始条目 ID
 */

import { setStatusCallback, prettyPrint } from './api/index.js';
import { initManualProcess } from './modules/manual-process.js';
import { initProcessTrace } from './modules/traces.js';
import { initTaskManager } from './modules/tasks.js';
import { initProcessedEntries, initProcessHistory } from './modules/entries.js';
import { initSavedEntries } from './modules/saved-entries.js';
import { initLLMMetrics, initFailedEntries, initLLMCalls, initLLMDuplicates } from './modules/metrics.js';

// 初始化应用
function initApp() {
  // 标签切换
  document.querySelectorAll('.tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      // 更新标签状态
      document.querySelectorAll('.tab').forEach(function(t) {
        t.classList.remove('active');
      });
      tab.classList.add('active');

      // 更新内容显示
      var tabName = tab.dataset.tab;
      document.querySelectorAll('.tab-content').forEach(function(content) {
        content.classList.toggle('active', content.dataset.tab === tabName);
      });
    });
  });

  // DOM 元素
  const originEl = document.getElementById('origin');
  const lastEl = document.getElementById('last');
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');

  originEl.textContent = window.location.origin;

  // 设置状态回调
  setStatusCallback(function (method, url, status, ms) {
    lastEl.textContent = `${method} ${url} -> ${status} (${ms}ms)`;

    if (status >= 500) {
      statusDot.className = 'status-dot error';
      statusText.textContent = '服务器错误';
    } else if (status >= 400) {
      statusDot.className = 'status-dot warning';
      statusText.textContent = '客户端错误';
    } else {
      statusDot.className = 'status-dot';
      statusText.textContent = '就绪';
    }

    setTimeout(function () {
      statusDot.className = 'status-dot';
      statusText.textContent = '就绪';
    }, 3000);
  });

  // ========== 处理追踪模块 ==========
  const traceModule = initProcessTrace({
    traceInput: document.getElementById('traceEntryId'),
    queryBtn: document.getElementById('btnTrace'),
    clearBtn: document.getElementById('btnClearTrace'),
    backBtn: document.getElementById('btnBackToTraceList'),
    outputEl: document.getElementById('outTrace'),
    summaryEl: document.getElementById('traceSummary'),
    timelineEl: document.getElementById('traceTimeline'),
    listEl: document.getElementById('traceList'),
    listBodyEl: document.getElementById('traceListBody'),
    statusEl: document.getElementById('traceStatus'),
    durationEl: document.getElementById('traceDuration'),
    stagesCountEl: document.getElementById('traceStagesCount'),
    canonicalIdEl: document.getElementById('traceCanonicalId'),
    categoryEl: document.getElementById('traceCategory')
  });

  // 辅助函数：跳转到追踪卡片
  function scrollToTraceCard() {
    const traceCard = document.getElementById('tracePanelCard');
    if (traceCard) {
      traceCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // ========== 手动处理模块 ==========
  initManualProcess({
    entryIdInput: document.getElementById('entryId'),
    triggerBtn: document.getElementById('btnManual'),
    outputEl: document.getElementById('outManual'),
    onTraceIdGenerated: function (traceId) {
      // 自动填充追踪 ID
      document.getElementById('traceEntryId').value = traceId;
      document.getElementById('outTrace').textContent = '等待处理日志...';
      document.getElementById('traceSummary').style.display = 'none';
      document.getElementById('traceTimeline').style.display = 'none';
      document.getElementById('traceList').style.display = 'none';
    }
  });

  // ========== LLM 指标模块 ==========
  const metricsModule = initLLMMetrics({
    loadBtn: document.getElementById('btnMetrics'),
    outputEl: document.getElementById('outMetrics')
  });

  // ========== LLM 调用记录模块 ==========
  const llmCallsModule = initLLMCalls({
    loadBtn: document.getElementById('btnLLMCalls'),
    tableBody: document.getElementById('llmCallsBody'),
    outputEl: document.getElementById('outLLMCalls'),
    canonicalIdInput: document.getElementById('llmCanonicalId'),
    agentFilter: document.getElementById('llmAgentFilter'),
    statusFilter: document.getElementById('llmStatusFilter'),
    limitInput: document.getElementById('llmCallsLimit'),
    statsEl: document.getElementById('llmCallsStats'),
    duplicatesResultEl: document.getElementById('llmDuplicatesResult'),
    onTraceRequest: function (canonicalId) {
      document.getElementById('traceEntryId').value = canonicalId;
      traceModule.loadTrace();
      scrollToTraceCard();
    }
  });

  // ========== LLM 重复调用检测模块 ==========
  initLLMDuplicates({
    loadBtn: document.getElementById('btnLLMDuplicates'),
    tableBody: document.getElementById('llmDuplicatesBody'),
    resultContainer: document.getElementById('llmDuplicatesResult'),
    outputEl: document.getElementById('outLLMCalls'),
    onCanonicalClick: function (canonicalId) {
      document.getElementById('llmCanonicalId').value = canonicalId;
      llmCallsModule.loadCalls();
    }
  });

  // ========== 失败条目模块 ==========
  initFailedEntries({
    loadBtn: document.getElementById('btnFailed'),
    clearAllBtn: document.getElementById('btnClearAll'),
    outputEl: document.getElementById('outFailed'),
    tableBody: document.getElementById('failedBody'),
    limitInput: document.getElementById('failedLimit'),
    onMetricsRefresh: function () {
      document.getElementById('btnMetrics').click();
    },
    onTraceRequest: function (id) {
      document.getElementById('traceEntryId').value = id;
      traceModule.loadTrace();
      scrollToTraceCard();
    }
  });

  // ========== 已处理条目模块 ==========
  initProcessedEntries({
    loadBtn: document.getElementById('btnProcessed'),
    refreshBtn: document.getElementById('btnRefreshProcessed'),
    outputEl: document.getElementById('outProcessed'),
    tableBody: document.getElementById('processedBody'),
    totalEl: document.getElementById('processedTotal'),
    rangeEl: document.getElementById('processedRange'),
    countEl: document.getElementById('processedCount'),
    limitInput: document.getElementById('processedLimit'),
    offsetInput: document.getElementById('processedOffset'),
    onTraceRequest: function (id) {
      document.getElementById('traceEntryId').value = id;
      traceModule.loadTrace();
      scrollToTraceCard();
    }
  });

  // ========== 保存条目检索模块 ==========
  initSavedEntries({
    searchBtn: document.getElementById('btnSavedEntriesSearch'),
    resetBtn: document.getElementById('btnSavedEntriesReset'),
    outputEl: document.getElementById('outSavedEntries'),
    tableBody: document.getElementById('savedEntriesBody'),
    totalEl: document.getElementById('savedEntriesTotal'),
    countEl: document.getElementById('savedEntriesCount'),
    rangeEl: document.getElementById('savedEntriesRange'),
    titleInput: document.getElementById('savedEntriesTitle'),
    matchSelect: document.getElementById('savedEntriesMatch'),
    limitInput: document.getElementById('savedEntriesLimit'),
    offsetInput: document.getElementById('savedEntriesOffset')
  });

  // ========== 任务管理模块 ==========
  initTaskManager({
    groupsLoadBtn: document.getElementById('btnTaskGroupsLoad'),
    statusFilter: document.getElementById('taskStatusFilter'),
    errorFilter: document.getElementById('taskErrorFilter'),
    groupLimit: document.getElementById('taskGroupLimit'),
    groupsBody: document.getElementById('taskGroupsBody'),
    groupsTotal: document.getElementById('taskGroupsTotal'),
    groupsCount: document.getElementById('taskGroupsCount'),
    currentGroupEl: document.getElementById('taskCurrentGroup'),

    samplesLoadBtn: document.getElementById('btnTaskSamplesLoad'),
    sampleLimit: document.getElementById('taskSampleLimit'),
    sampleOffset: document.getElementById('taskSampleOffset'),
    sampleIncludePayload: document.getElementById('taskSampleIncludePayload'),
    samplesBody: document.getElementById('taskSamplesBody'),
    samplesTotal: document.getElementById('taskSamplesTotal'),
    samplesCount: document.getElementById('taskSamplesCount'),
    detailIdInput: document.getElementById('taskDetailId'),
    detailLoadBtn: document.getElementById('btnTaskDetailLoad'),

    filterRequeueBtn: document.getElementById('btnTaskFilterRequeue'),
    groupRequeueBtn: document.getElementById('btnTaskGroupRequeue'),

    outputEl: document.getElementById('outTaskOps')
  });

  // ========== 处理历史模块 ==========
  const historyModule = initProcessHistory({
    loadBtn: document.getElementById('btnHistory'),
    refreshBtn: document.getElementById('btnRefreshHistory'),
    outputEl: document.getElementById('outHistory'),
    tableBody: document.getElementById('historyBody'),
    limitInput: document.getElementById('historyLimit'),
    totalEl: document.getElementById('historyTotal'),
    countEl: document.getElementById('historyCount'),
    searchInput: document.getElementById('historySearchQuery'),
    searchBtn: document.getElementById('btnHistorySearch'),
    searchClearBtn: document.getElementById('btnHistorySearchClear'),
    searchStatusEl: document.getElementById('historySearchStatus'),
    onBatchClick: function (traceId) {
      // 点击批次后，填充 trace_id 并加载批次详情
      document.getElementById('traceEntryId').value = traceId;
      traceModule.loadTrace();
      scrollToTraceCard();
    }
  });

  // 页面加载时自动加载处理历史
  historyModule.loadHistory();

  // ========== 全局快捷操作 ==========
  const btnGlobalRefresh = document.getElementById('btnGlobalRefresh');
  const btnGlobalClearOutput = document.getElementById('btnGlobalClearOutput');

  if (btnGlobalRefresh) {
    btnGlobalRefresh.addEventListener('click', function () {
      document.getElementById('btnMetrics')?.click();
      document.getElementById('btnTaskGroupsLoad')?.click();
      document.getElementById('btnHistory')?.click();
      document.getElementById('btnSavedEntriesSearch')?.click();
    });
  }

  if (btnGlobalClearOutput) {
    btnGlobalClearOutput.addEventListener('click', function () {
      [
        'outManual',
        'outTrace',
        'outMetrics',
        'outFailed',
        'outProcessed',
        'outTaskOps',
        'outHistory',
        'outLLMCalls',
        'outSavedEntries'
      ].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) {
          el.textContent = '';
        }
      });
    });
  }
}

// DOM 加载完成后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
