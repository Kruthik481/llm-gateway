'use client';

import { Bar } from '@/components/charts/bar';
import { BarChart } from '@/components/charts/bar-chart';
import { BarXAxis } from '@/components/charts/bar-x-axis';
import { ChartTooltip } from '@/components/charts/tooltip';
import { cardClass } from '@/lib/styles';

type Row = { name: string; requests: number; tokens: number };

export function DailyChart({ rows, dataKey, label }: { rows: Row[]; dataKey: 'requests' | 'tokens'; label: string }) {
  return (
    <figure className={cardClass}>
      <figcaption className="text-sm text-muted">{label}</figcaption>
      <BarChart
        data={rows}
        xDataKey="name"
        aspectRatio="3 / 1"
        barGap={0.3}
        margin={{ top: 8, right: 8, bottom: 24, left: 8 }}
      >
        <Bar dataKey={dataKey} fill="var(--accent)" lineCap={3} />
        <BarXAxis />
        <ChartTooltip />
      </BarChart>
    </figure>
  );
}
