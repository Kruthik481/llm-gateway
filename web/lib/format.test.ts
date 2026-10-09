import { describe, expect, it } from 'vitest';
import { formatDateTime, formatMs, formatPercent, formatTokens, formatUsd } from './format';

describe('formatUsd', () => {
  it('shows small list-price costs with four decimals', () => {
    expect(formatUsd('0.00120000')).toBe('$0.0012');
    expect(formatUsd('0.00004')).toBe('<$0.0001');
    expect(formatUsd('0')).toBe('$0');
    expect(formatUsd('12.5')).toBe('$12.50');
  });
});

describe('formatTokens', () => {
  it('abbreviates thousands and millions', () => {
    expect(formatTokens(999)).toBe('999');
    expect(formatTokens(1234)).toBe('1.2k');
    expect(formatTokens(12_345)).toBe('12k');
    expect(formatTokens(2_500_000)).toBe('2.5M');
  });
});

describe('formatMs / formatPercent / formatDateTime', () => {
  it('formats durations, rates and UTC timestamps', () => {
    expect(formatMs(null)).toBe('—');
    expect(formatMs(240.4)).toBe('240 ms');
    expect(formatMs(1500)).toBe('1.5 s');
    expect(formatPercent(0.4567)).toBe('45.7%');
    expect(formatDateTime('2026-10-09T14:05:00Z')).toBe('9 Oct 2026, 14:05 UTC');
  });
});
