import { describe, expect, it } from 'vitest';

import { renderTimeline } from './traces.js';

describe('renderTimeline', () => {
  it('shows zero-duration stages and keeps short canonical ids intact', () => {
    const container = document.createElement('div');

    renderTimeline(
      [
        {
          stage: 'process',
          action: 'complete',
          status: 'success',
          timestamp: '2026-04-18T00:00:00Z',
          duration_ms: 0,
          data: {
            canonical_id: 'canon-short',
          },
        },
      ],
      container
    );

    expect(container.textContent).toContain('0ms');
    expect(container.textContent).toContain('canon-short');
    expect(container.textContent).not.toContain('canon-short...');
  });
});
