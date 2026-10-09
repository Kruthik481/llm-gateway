import { formatDateTime, formatMs, formatUsd } from '@/lib/format';
import type { RecentRow } from '@/lib/types';

const STATUS_CLASS: Record<RecentRow['status'], string> = {
  ok: 'text-ok',
  partial: 'text-warn',
  error: 'text-danger',
};

export function RecentTable({ rows }: { rows: RecentRow[] }) {
  if (rows.length === 0) return <p className="mt-4 text-sm text-muted">No requests yet. Try the playground.</p>;
  return (
    <table aria-label="Recent requests" className="mt-4 w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-muted">
        <tr>
          <th className="py-2">Time</th>
          <th>Key</th>
          <th>Model</th>
          <th>Provider</th>
          <th className="text-right">Tokens</th>
          <th className="text-right">List cost</th>
          <th className="text-right">Latency</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.created_at}-${row.key_prefix}`} className="border-t border-line">
            <td className="py-2">{formatDateTime(row.created_at)}</td>
            <td className="font-mono text-muted">{row.key_prefix}…</td>
            <td>{row.model}</td>
            <td>
              {row.cache_hit ? 'cache' : (row.provider ?? '—')}
              {row.attempts > 1 && <span className="ml-1 text-xs text-warn">fallback</span>}
            </td>
            <td className="text-right tabular-nums">{row.prompt_tokens + row.completion_tokens}</td>
            <td className="text-right tabular-nums">{formatUsd(row.cost_usd)}</td>
            <td className="text-right tabular-nums">{formatMs(row.latency_ms)}</td>
            <td className={STATUS_CLASS[row.status]}>{row.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
