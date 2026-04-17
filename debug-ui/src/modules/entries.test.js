import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockRequest = vi.fn();
const mockSearchProcessHistory = vi.fn();

vi.mock('../api/index.js', async () => {
  const actual = await vi.importActual('../api/index.js');
  return {
    ...actual,
    request: mockRequest,
    searchProcessHistory: mockSearchProcessHistory,
  };
});

const { initProcessHistory } = await import('./entries.js');

function createButton() {
  const button = document.createElement('button');
  button.disabled = false;
  return button;
}

function createBaseOptions() {
  return {
    loadBtn: createButton(),
    refreshBtn: createButton(),
    outputEl: document.createElement('pre'),
    tableBody: document.createElement('tbody'),
    limitInput: Object.assign(document.createElement('input'), { value: '20' }),
    totalEl: document.createElement('span'),
    countEl: document.createElement('span'),
    onBatchClick: vi.fn(),
    searchInput: Object.assign(document.createElement('input'), { value: '' }),
    searchBtn: createButton(),
    searchClearBtn: createButton(),
    searchStatusEl: undefined,
  };
}

describe('initProcessHistory', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    mockRequest.mockReset();
    mockSearchProcessHistory.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders short trace ids without fake ellipsis and preserves zero durations', async () => {
    mockRequest.mockResolvedValue({
      status: 'ok',
      total: 1,
      traces: [
        {
          trace_id: 'short-trace',
          status: 'success',
          success_count: 1,
          error_count: 0,
          total_entries: 1,
          duration_ms: 0,
          start_time: '2026-04-18T00:00:00Z',
        },
      ],
    });

    const options = createBaseOptions();
    const { loadHistory } = initProcessHistory(options);

    await loadHistory();

    const cells = options.tableBody.querySelectorAll('td');
    expect(cells[0].textContent).toBe('short-trace');
    expect(cells[3].textContent).toBe('0ms');
  });

  it('allows search interactions when searchStatusEl is omitted', async () => {
    mockSearchProcessHistory.mockResolvedValue({
      status: 'ok',
      query: '123',
      query_type: 'entry_id',
      total: 0,
      traces: [],
    });

    const options = createBaseOptions();
    options.searchInput.value = '123';
    initProcessHistory(options);

    options.searchBtn.click();
    await Promise.resolve();
    await Promise.resolve();

    expect(mockSearchProcessHistory).toHaveBeenCalledWith('123');
    expect(options.searchBtn.disabled).toBe(false);
  });
});
