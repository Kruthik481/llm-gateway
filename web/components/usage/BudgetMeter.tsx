import { formatTokens } from '@/lib/format';
import { cardClass } from '@/lib/styles';
import { budgetPercent } from '@/lib/usage';

export function BudgetMeter({ used, limit }: { used: number; limit: number }) {
  const percent = budgetPercent(used, limit);
  return (
    <div className={cardClass}>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted">Today&apos;s token budget</span>
        <span className="tabular-nums">
          {formatTokens(used)} / {formatTokens(limit)}
        </span>
      </div>
      <div
        role="meter"
        aria-label="Daily token budget used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-3 h-2 overflow-hidden rounded-full bg-bg"
      >
        <div className={`h-full ${percent >= 90 ? 'bg-danger' : 'bg-accent'}`} style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted">Resets at 00:00 UTC.</p>
    </div>
  );
}
