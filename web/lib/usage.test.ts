import { describe, expect, it } from 'vitest';
import { budgetPercent, chartRows, totalCost } from './usage';

describe('usage helpers', () => {
  it('clamps the budget meter', () => {
    expect(budgetPercent(12_500, 50_000)).toBe(25);
    expect(budgetPercent(60_000, 50_000)).toBe(100);
    expect(budgetPercent(5, 0)).toBe(0);
  });

  it('sums decimal-string costs', () => {
    expect(totalCost([{ cost_usd: '0.00120000' }, { cost_usd: '0.00030000' }])).toBeCloseTo(0.0015, 8);
  });

  it('labels chart rows by month and day', () => {
    expect(chartRows([{ day: '2026-10-09', requests: 3, tokens: 90 }])).toEqual([
      { name: '10-09', requests: 3, tokens: 90 },
    ]);
  });
});
