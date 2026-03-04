/**
 * save_entry 条目查询模块
 */

import { getSavedEntries, prettyPrint, formatUnixSeconds, parsePositiveInt } from '../api/index.js';
import { showEmptyTableRow } from './ui.js';

/**
 * 初始化保存条目查询模块
 * @param {Object} options - 配置项
 */
export function initSavedEntries(options) {
  const {
    searchBtn,
    resetBtn,
    outputEl,
    tableBody,
    totalEl,
    countEl,
    rangeEl,
    titleInput,
    matchSelect,
    limitInput,
    offsetInput
  } = options;

  function renderRows(entries) {
    tableBody.innerHTML = '';

    if (!entries || entries.length === 0) {
      tableBody.appendChild(showEmptyTableRow(8, '📭', '未找到匹配的保存条目'));
      return;
    }

    entries.forEach(function (item) {
      const tr = document.createElement('tr');

      const tdCanonical = document.createElement('td');
      tdCanonical.className = 'mono';
      tdCanonical.style.fontSize = '11px';
      tdCanonical.textContent = item.canonical_id || '-';
      tr.appendChild(tdCanonical);

      const tdEntryId = document.createElement('td');
      tdEntryId.className = 'mono';
      tdEntryId.textContent = item.entry_id || '-';
      tr.appendChild(tdEntryId);

      const tdTitle = document.createElement('td');
      tdTitle.className = 'saved-title-cell';
      const fullTitle = item.title || '-';
      tdTitle.textContent = fullTitle.length > 90 ? fullTitle.slice(0, 90) + '...' : fullTitle;
      tdTitle.title = fullTitle;
      tr.appendChild(tdTitle);

      const tdFeedTitle = document.createElement('td');
      tdFeedTitle.textContent = item.feed_title || '未知来源';
      tdFeedTitle.title = item.feed_title || '';
      tr.appendChild(tdFeedTitle);

      const tdCount = document.createElement('td');
      tdCount.className = 'mono';
      tdCount.textContent = String(item.save_count || 0);
      tr.appendChild(tdCount);

      const tdFirst = document.createElement('td');
      tdFirst.textContent = formatUnixSeconds(item.first_saved_at);
      tr.appendChild(tdFirst);

      const tdLast = document.createElement('td');
      tdLast.textContent = formatUnixSeconds(item.last_saved_at);
      tr.appendChild(tdLast);

      const tdUrl = document.createElement('td');
      if (item.url) {
        const link = document.createElement('a');
        link.className = 'link';
        link.href = item.url;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = '打开';
        tdUrl.appendChild(link);
      } else {
        tdUrl.textContent = '-';
      }
      tr.appendChild(tdUrl);

      tableBody.appendChild(tr);
    });
  }

  async function loadSavedEntries() {
    outputEl.textContent = '';
    searchBtn.disabled = true;
    resetBtn.disabled = true;

    const title = String(titleInput.value || '').trim();
    const match = String(matchSelect.value || 'prefix').trim();
    const limit = parsePositiveInt(limitInput.value, 50);
    const offset = Math.max(0, parseInt((offsetInput.value || '0').trim(), 10) || 0);

    try {
      const data = await getSavedEntries({ title, match, limit, offset });

      outputEl.textContent = prettyPrint({
        status: data.status,
        title_filter: data.title_filter,
        match: data.match,
        total: data.total,
        returned: data.count
      });

      const total = Number(data.total || 0);
      const count = Number(data.count || 0);
      totalEl.textContent = String(total);
      countEl.textContent = String(count);
      if (total === 0 || count === 0) {
        rangeEl.textContent = '0-0';
      } else {
        rangeEl.textContent = `${offset + 1}-${offset + count}`;
      }

      renderRows(data.entries || []);
    } catch (e) {
      outputEl.textContent = prettyPrint({ error: e.message, response: e.response || null });
    } finally {
      searchBtn.disabled = false;
      resetBtn.disabled = false;
    }
  }

  function resetSearch() {
    titleInput.value = '';
    matchSelect.value = 'prefix';
    limitInput.value = '50';
    offsetInput.value = '0';
    totalEl.textContent = '0';
    countEl.textContent = '0';
    rangeEl.textContent = '0-0';
    outputEl.textContent = '';
    tableBody.innerHTML = '';
    tableBody.appendChild(showEmptyTableRow(8, '📥', '点击“加载”查看保存条目，或输入标题进行过滤'));
  }

  searchBtn.addEventListener('click', loadSavedEntries);
  resetBtn.addEventListener('click', resetSearch);
  titleInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter') {
      loadSavedEntries();
    }
  });

  return { loadSavedEntries, resetSearch };
}
