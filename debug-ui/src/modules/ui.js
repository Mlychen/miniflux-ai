/**
 * UI 组件工具模块
 */

/**
 * 获取状态徽章样式类
 * @param {string} status - 状态值
 * @returns {string} 徽章 CSS 类名
 */
export function getStatusBadgeClass(status) {
  const map = {
    'success': 'badge-success',
    'error': 'badge-error',
    'pending': 'badge-warning',
    'skipped': 'badge-info',
    'retryable': 'badge-warning',
    'dead': 'badge-error',
    'running': 'badge-info',
    'done': 'badge-success'
  };
  return map[status] || 'badge-info';
}

/**
 * 获取状态徽章 HTML
 * @param {string} status - 状态值
 * @returns {string} HTML 字符串
 */
export function getStatusBadge(status) {
  const map = {
    'failed': 'error',
    'pending': 'warning',
    'processing': 'info',
    'success': 'success',
    'retryable': 'warning',
    'dead': 'error',
    'running': 'info',
    'done': 'success'
  };
  const type = map[status] || 'info';
  return `<span class="badge badge-${type}">${status || 'unknown'}</span>`;
}

/**
 * 获取任务状态徽章 HTML
 * @param {string} status - 任务状态
 * @returns {string} HTML 字符串
 */
export function getTaskStatusBadge(status) {
  if (status === 'retryable') {
    return '<span class="badge badge-warning">retryable</span>';
  }
  if (status === 'dead') {
    return '<span class="badge badge-error">dead</span>';
  }
  if (status === 'running') {
    return '<span class="badge badge-info">running</span>';
  }
  if (status === 'done') {
    return '<span class="badge badge-success">done</span>';
  }
  return `<span class="badge badge-info">${status || 'unknown'}</span>`;
}

/**
 * 获取类别徽章 HTML
 * @param {string} category - 类别
 * @returns {string} HTML 字符串
 */
export function getCategoryBadge(category) {
  if (!category || category === '-') {
    return '<span class="category-tag">未分类</span>';
  }
  const colors = {
    '科技': 'info',
    'AI': 'success',
    '产品': 'warning',
    '研究': 'error'
  };
  const type = colors[category] || 'info';
  return `<span class="badge badge-${type}">${category}</span>`;
}

/**
 * 创建按钮元素
 * @param {string} text - 按钮文本
 * @param {string} className - CSS 类名
 * @param {Function} onClick - 点击回调
 * @returns {HTMLButtonElement} 按钮元素
 */
export function createButton(text, className = 'btn', onClick = null) {
  const btn = document.createElement('button');
  btn.className = className;
  btn.textContent = text;
  if (onClick) {
    btn.addEventListener('click', onClick);
  }
  return btn;
}

/**
 * 设置按钮加载状态
 * @param {HTMLButtonElement} button - 按钮元素
 * @param {boolean} loading - 是否加载中
 * @param {string} loadingText - 加载时文本
 * @param {string} normalText - 正常文本
 */
export function setButtonLoading(button, loading, loadingText = '加载中...', normalText = '') {
  button.disabled = loading;
  if (loading) {
    button.innerHTML = '<div class="spinner"></div> ' + loadingText;
  } else if (normalText) {
    button.textContent = normalText;
  }
}

/**
 * 显示空状态表格行
 * @param {number} colspan - 跨列数
 * @param {string} icon - 图标 emoji
 * @param {string} text - 提示文本
 * @returns {HTMLTableRowElement} 表格行元素
 */
export function showEmptyTableRow(colspan, icon, text) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td colspan="${colspan}" class="empty-state">
      <div class="empty-state-icon">${icon}</div>
      <div class="empty-state-text">${text}</div>
    </td>
  `;
  return tr;
}