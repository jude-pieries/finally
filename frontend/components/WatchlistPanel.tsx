'use client';

import { useState } from 'react';
import { WatchlistRow } from './WatchlistRow';
import { useWatchlist } from '@/hooks/useWatchlist';

type WatchlistPanelProps = {
  selectedTicker: string | null;
  onSelectTicker: (ticker: string) => void;
};

export function WatchlistPanel({
  selectedTicker,
  onSelectTicker,
}: WatchlistPanelProps) {
  const { tickers, addTicker, removeTicker } = useWatchlist();
  const [addInput, setAddInput] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const ticker = addInput.trim().toUpperCase();
    if (!ticker) return;
    setAdding(true);
    setAddError(null);
    const result = await addTicker(ticker);
    setAdding(false);
    if (result.success) {
      setAddInput('');
    } else {
      setAddError(result.error || 'Failed to add ticker');
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#161b22] border-r border-[#30363d] w-56 min-w-56">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#30363d]">
        <span className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">
          Watchlist
        </span>
        <span className="text-xs text-[#8b949e]">{tickers.length}</span>
      </div>

      {/* Ticker list */}
      <div className="flex-1 overflow-y-auto group">
        {tickers.map((ticker) => (
          <WatchlistRow
            key={ticker}
            ticker={ticker}
            isSelected={selectedTicker === ticker}
            onSelect={onSelectTicker}
            onRemove={removeTicker}
          />
        ))}
        {tickers.length === 0 && (
          <div className="px-3 py-4 text-xs text-[#8b949e] text-center">
            No tickers in watchlist
          </div>
        )}
      </div>

      {/* Add ticker form */}
      <div className="border-t border-[#30363d] p-3">
        <form onSubmit={handleAdd} className="flex gap-1">
          <input
            type="text"
            value={addInput}
            onChange={(e) => setAddInput(e.target.value.toUpperCase())}
            placeholder="Add ticker..."
            className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs font-mono text-[#e6edf3] placeholder-[#8b949e] focus:outline-none focus:border-[#209dd7] min-w-0"
            maxLength={10}
          />
          <button
            type="submit"
            disabled={adding || !addInput.trim()}
            className="bg-[#209dd7] text-white text-xs px-2 py-1 rounded disabled:opacity-50 hover:bg-[#1a8abf] transition-colors font-semibold"
          >
            +
          </button>
        </form>
        {addError && (
          <p className="text-[#f85149] text-xs mt-1">{addError}</p>
        )}
      </div>
    </div>
  );
}
