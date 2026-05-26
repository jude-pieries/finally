'use client';

import React from 'react';
import { Treemap, ResponsiveContainer, Tooltip } from 'recharts';
import { usePrices } from '@/contexts/PriceContext';
import type { Portfolio } from '@/types';
import type { TreemapNode } from 'recharts/types/chart/Treemap';

type HeatmapProps = {
  portfolio: Portfolio | null;
};

function pnlColor(pnlPercent: number): string {
  const intensity = Math.min(Math.abs(pnlPercent) / 10, 1);
  if (pnlPercent >= 0) {
    const r = Math.round(20 + (63 - 20) * intensity);
    const g = Math.round(80 + (185 - 80) * intensity);
    const b = Math.round(30 + (80 - 30) * intensity);
    return `rgb(${r},${g},${b})`;
  } else {
    const r = Math.round(80 + (248 - 80) * intensity);
    const g = Math.round(20 + (81 - 20) * intensity);
    const b = Math.round(20 + (73 - 20) * intensity);
    return `rgb(${r},${g},${b})`;
  }
}

function renderTreemapContent(props: TreemapNode): React.ReactElement {
  const { x, y, width, height, name } = props;
  const pnlPercent = (props['pnlPercent'] as number) ?? 0;
  const color = pnlColor(pnlPercent);
  const showText = width > 40 && height > 30;

  return (
    <g>
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(width - 2, 0)}
        height={Math.max(height - 2, 0)}
        style={{ fill: color, stroke: '#0d1117', strokeWidth: 2 }}
        rx={2}
      />
      {showText && (
        <>
          <text
            x={x + width / 2}
            y={y + height / 2 - 6}
            textAnchor="middle"
            fill="#e6edf3"
            fontSize={Math.min(12, width / 4)}
            fontFamily="monospace"
            fontWeight="bold"
          >
            {name}
          </text>
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill="rgba(230,237,243,0.8)"
            fontSize={Math.min(10, width / 5)}
            fontFamily="monospace"
          >
            {pnlPercent >= 0 ? '+' : ''}
            {pnlPercent.toFixed(2)}%
          </text>
        </>
      )}
    </g>
  );
}

export function PortfolioHeatmap({ portfolio }: HeatmapProps) {
  const { prices } = usePrices();

  if (!portfolio || portfolio.positions.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[#8b949e] text-sm text-center px-4">
        No positions yet. Buy some stocks to see your portfolio heatmap.
      </div>
    );
  }

  const data = portfolio.positions.map((pos) => {
    const livePrice = prices[pos.ticker]?.price ?? pos.current_price;
    const value = pos.quantity * livePrice;
    const pnlPct =
      pos.avg_cost > 0
        ? ((livePrice - pos.avg_cost) / pos.avg_cost) * 100
        : 0;
    const pnl = (livePrice - pos.avg_cost) * pos.quantity;

    return {
      name: pos.ticker,
      size: Math.max(value, 1),
      value: value,
      pnlPercent: pnlPct,
      pnl,
    };
  });

  return (
    <ResponsiveContainer width="100%" height="100%">
      <Treemap
        data={data}
        dataKey="size"
        nameKey="name"
        aspectRatio={4 / 3}
        content={renderTreemapContent}
      >
        <Tooltip
          contentStyle={{
            backgroundColor: '#1c2128',
            border: '1px solid #30363d',
            borderRadius: '4px',
            fontFamily: 'monospace',
            fontSize: '12px',
          }}
          formatter={(value, name) => {
            const v = Number(value);
            return [`$${v.toFixed(2)}`, String(name)];
          }}
        />
      </Treemap>
    </ResponsiveContainer>
  );
}
