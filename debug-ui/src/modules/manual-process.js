/**
 * 手动处理模块
 */

import {
  request,
  prettyPrint,
  generateTraceId,
  API
} from '../api/index.js';

/**
 * 初始化手动处理模块
 * @param {Object} options - 配置选项
 * @param {HTMLInputElement} options.entryIdInput - Entry ID 输入框
 * @param {HTMLButtonElement} options.triggerBtn - 触发按钮
 * @param {HTMLElement} options.outputEl - 输出元素
 * @param {Function} options.onTraceIdGenerated - Trace ID 生成回调
 */
export function initManualProcess(options) {
  const {
    entryIdInput,
    triggerBtn,
    outputEl,
    onTraceIdGenerated
  } = options;

  triggerBtn.addEventListener('click', async function () {
    const entryId = (entryIdInput.value || '').trim();
    outputEl.textContent = '';

    if (!entryId) {
      outputEl.textContent = '请输入 entry_id';
      return;
    }

    const traceId = generateTraceId();

    // 回调通知外部
    if (onTraceIdGenerated) {
      onTraceIdGenerated(traceId);
    }

    triggerBtn.disabled = true;
    triggerBtn.innerHTML = '<div class="spinner"></div> 处理中...';

    try {
      const data = await request('POST', API.manualProcess, {
        entry_id: entryId,
        trace_id: traceId
      });

      outputEl.textContent = prettyPrint(data);

      // 返回结果供外部处理
      return { success: true, data, traceId };
    } catch (e) {
      outputEl.textContent = prettyPrint({
        error: e.message,
        response: e.response || null
      });
      return { success: false, error: e };
    } finally {
      triggerBtn.disabled = false;
      triggerBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M11.742 5.5a.5.5 0 10-.744.67l1.902 2.113-1.902 2.113a.5.5 0 00.744.67l2.25-2.5a.5.5 0 000-.67l-2.25-2.5zM2 8.5a6.5 6.5 0 1111.32 4.33.5.5 0 11-.64-.766A5.5 5.5 0 103 8.5a.5.5 0 01-1 0z"/>
        </svg>
        触发处理
      `;
    }
  });
}