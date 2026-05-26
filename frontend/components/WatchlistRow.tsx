'use client';

import { usePrices } from '@/contexts/PriceContext';
import { Sparkline } from './Sparkline';

type WatchlistRowProps = {
  ticker: string;
  isSelected: boolean;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
};

export function WatchlistRow({
  ticker,
  isSelected,
  onSelect,
  onRemove,
}: WatchlistRowProps) {
  const { prices, sparklines, flashState } = usePrices();
  const priceData = prices[ticker];
  const sparkData = sparklines[ticker] || [];
  const flash = flashState[ticker];

  const price = priceData?.price ?? null;
  const openPrice = priceData?.open_price ?? null;
  const dailyChange =
    price !== null && openPrice !== null && openPrice !== 0
      ? ((price - openPrice) / openPrice) * 100
      : null;

  const isUp = dailyChange !== null ? dailyChange >= 0 : true;
  const flashClass = flash === 'up' ? 'flash-up' : flash === 'down' ? 'flash-down' : '';

  return (
    <div
      className={`flex flex-col px-3 py-2 cursor-pointer border-b border-[#30363d] hover:bg-[#1c2128] transition-colors ${
        isSelected ? 'bg-[#1c2128] border-l-2 border-l-[#209dd7]' : ''
      } ${flashClass}`}
      onClick={() => onSelect(ticker)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-[#e6edf3]">
            {ticker}
          </span>
          <div className="opacity-70">
            <Sparkline data={sparkData} isUp={isUp} />
          </div>
        </div>
        <button
          className="text-[#8b949e] hover:text-[#f85149] text-xs opacity-0 group-hover:opacity-100 transition-opacity ml-1"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(ticker);
          }}
          title="Remove from watchlist"
        >
          ×
        </button>
      </div>
      <div className="flex items-center justify-between mt-0.5">
        <span className="font-mono text-sm text-[#e6edf3]">
          {price !== null ? `$${price.toFixed(2)}` : '—'}
        </span>
        <span
          className={`font-mono text-xs ${
            dailyChange === null
              ? 'text-[#8b949e]'
              : isUp
              ? 'text-[#3fb950]'
              : 'text-[#f85149]'
          }`}
        >
          {dailyChange !== null
            ? `${dailyChange >= 0 ? '+' : ''}${dailyChange.toFixed(2)}%`
            : '—'}
        </span>
      </div>
    </div>
  );
}
