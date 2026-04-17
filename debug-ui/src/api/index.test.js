import { describe, expect, it } from 'vitest';

import { formatDuration, truncateIdentifier } from './index.js';

describe('truncateIdentifier', () => {
  it('returns a placeholder for empty values', () => {
    expect(truncateIdentifier('')).toBe('-');
    expect(truncateIdentifier(null)).toBe('-');
  });

  it('keeps short identifiers unchanged', () => {
    expect(truncateIdentifier('short-id', 16)).toBe('short-id');
  });

  it('truncates long identifiers only when needed', () => {
    expect(truncateIdentifier('1234567890abcdefXYZ', 16)).toBe('1234567890abcdef...');
  });
});

describe('formatDuration', () => {
  it('preserves zero durations', () => {
    expect(formatDuration(0)).toBe('0ms');
  });

  it('returns a placeholder for missing durations', () => {
    expect(formatDuration(undefined)).toBe('-');
    expect(formatDuration(null)).toBe('-');
  });
});
