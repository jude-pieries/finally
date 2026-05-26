'use client';

import { usePrices } from '@/contexts/PriceContext';
import type { Portfolio } from '@/types';

type PositionsTableProps = {
  portfolio: Portfolio | null;
  onTickerClick?: (ticker: string) => void;
};

export function PositionsTable({ portfolio, onTickerClick }: PositionsTableProps) {
  const { prices } = usePrices();

  if (!portfolio || portfolio.positions.length === 0) {
    return (
      <div className="flex items-center justify-center h-16 text-[#8b949e] text-sm">
        No positions. Use the trade bar below to buy shares.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[#8b949e] uppercase tracking-wider border-b border-[#30363d]">
            <th className="text-left px-3 py-2 font-semibold">Ticker</th>
            <th className="text-right px-3 py-2 font-semibold">Qty</th>
            <th className="text-right px-3 py-2 font-semibold">Avg Cost</th>
            <th className="text-right px-3 py-2 font-semibold">Price</th>
            <th className="text-right px-3 py-2 font-semibold">Value</th>
            <th className="text-right px-3 py-2 font-semibold">P&L</th>
            <th className="text-right px-3 py-2 font-semibold">P&L %</th>
            <th className="text-right px-3 py-2 font-semibold">Daily %</th>
          </tr>
        </thead>
        <tbody>
          {portfolio.positions.map((pos) => {
            const liveData = prices[pos.ticker];
            const livePrice = liveData?.price ?? pos.current_price;
            const openPrice = liveData?.open_price;
            const pnl = (livePrice - pos.avg_cost) * pos.quantity;
            const pnlPct =
              pos.avg_cost > 0
                ? ((livePrice - pos.avg_cost) / pos.avg_cost) * 100
                : 0;
            const dailyPct =
              openPrice && openPrice > 0
                ? ((livePrice - openPrice) / openPrice) * 100
                : pos.daily_change_percent;
            const value = pos.quantity * livePrice;
            const isProfit = pnl >= 0;

            return (
              <tr
                key={pos.ticker}
                className={`border-b border-[#30363d] transition-colors hover:bg-[#1c2128] cursor-pointer ${
                  isProfit ? 'bg-[#3fb950]/5' : 'bg-[#f85149]/5'
                }`}
                onClick={() => onTickerClick?.(pos.ticker)}
              >
                <td className="px-3 py-2">
                  <span className="font-mono font-semibold text-[#e6edf3]">
                    {pos.ticker}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono text-[#e6edf3]">
                  {pos.quantity % 1 === 0
                    ? pos.quantity.toFixed(0)
                    : pos.quantity.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[#8b949e]">
                  ${pos.avg_cost.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[#e6edf3]">
                  ${livePrice.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[#e6edf3]">
                  ${value.toFixed(2)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono font-medium ${
                    isProfit ? 'text-[#3fb950]' : 'text-[#f85149]'
                  }`}
                >
                  {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono ${
                    pnlPct >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                  }`}
                >
                  {pnlPct >= 0 ? '+' : ''}
                  {pnlPct.toFixed(2)}%
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono ${
                    (dailyPct ?? 0) >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                  }`}
                >
                  {dailyPct !== null && dailyPct !== undefined
                    ? `${dailyPct >= 0 ? '+' : ''}${dailyPct.toFixed(2)}%`
                    : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
