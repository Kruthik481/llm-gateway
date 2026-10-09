import { Stat } from '@/components/Stat';
import { BudgetMeter } from '@/components/usage/BudgetMeter';
import { DailyChart } from '@/components/usage/DailyChart';
import { RecentTable } from '@/components/usage/RecentTable';
import { control } from '@/lib/control';
import { formatMs, formatTokens, formatUsd } from '@/lib/format';
import { cardClass } from '@/lib/styles';
import type { RecentRow, UsageSummary } from '@/lib/types';
import { chartRows, totalCost } from '@/lib/usage';

const DAYS = 14;

export const metadata = { title: 'Usage · LLM Gateway' };

export default async function UsagePage() {
  const [summary, recent] = await Promise.all([
    control<UsageSummary>(`/control/usage/summary?days=${DAYS}`),
    control<RecentRow[]>('/control/usage/recent?limit=50'),
  ]);
  const rows = chartRows(summary.days);
  const requests = summary.days.reduce((n, d) => n + d.requests, 0);
  const tokens = summary.days.reduce((n, d) => n + d.tokens, 0);
  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Usage</h1>
      <p className="mt-1 text-sm text-muted">
        Last {DAYS} days. Costs are list-price equivalents; the free tiers bill $0.
      </p>
      <div className="mt-6 grid gap-4 md:grid-cols-[2fr_3fr]">
        <BudgetMeter used={summary.budget.used} limit={summary.budget.limit} />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Requests" value={String(requests)} />
          <Stat label="Tokens" value={formatTokens(tokens)} />
          <Stat label="List-price cost" value={formatUsd(totalCost(summary.cost_by_model))} />
          <Stat label="Saved by cache" value={formatUsd(summary.cache_saved_usd)} />
        </div>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <DailyChart rows={rows} dataKey="requests" label="Requests per day" />
        <DailyChart rows={rows} dataKey="tokens" label="Tokens per day" />
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <Stat
          label="Latency p50 / p95"
          value={`${formatMs(summary.latency_ms.p50)} / ${formatMs(summary.latency_ms.p95)}`}
        />
        <Stat label="TTFT p50 / p95" value={`${formatMs(summary.ttft_ms.p50)} / ${formatMs(summary.ttft_ms.p95)}`} />
        <Stat label="Fallbacks" value={String(summary.fallbacks)} hint="Answered after a provider failed" />
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section aria-label="Cost by model" className={cardClass}>
          <h2 className="text-sm text-muted">List-price cost by model</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {summary.cost_by_model.map((m) => (
              <li key={m.model} className="flex justify-between">
                <span>{m.model}</span>
                <span className="tabular-nums">{formatUsd(m.cost_usd)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="Providers" className={cardClass}>
          <h2 className="text-sm text-muted">Answered by provider (excluding cache)</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {summary.providers.map((p) => (
              <li key={p.provider} className="flex justify-between">
                <span>{p.provider}</span>
                <span className="tabular-nums">{p.requests}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <h2 className="mt-10 text-lg font-semibold">Recent requests</h2>
      <RecentTable rows={recent} />
    </main>
  );
}
