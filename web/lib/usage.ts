import type { UsageSummary } from './types';

export function budgetPercent(used: number, limit: number): number {
  if (limit <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((used / limit) * 100)));
}

export function totalCost(rows: { cost_usd: string }[]): number {
  return rows.reduce((sum, row) => sum + Number(row.cost_usd), 0);
}

export function chartRows(days: UsageSummary['days']) {
  return days.map((d) => ({ name: d.day.slice(5), requests: d.requests, tokens: d.tokens }));
}
