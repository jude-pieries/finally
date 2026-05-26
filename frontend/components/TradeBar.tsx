'use client';

import { useState, useEffect } from 'react';
import { usePrices } from '@/contexts/PriceContext';
import type { Portfolio } from '@/types';

type TradeBarProps = {
  portfolio: Portfolio | null;
  selectedTicker: string | null;
  onTradeComplete: () => void;
};

type TradeMessage = {
  type: 'success' | 'error';
  text: string;
};

export function TradeBar({
  portfolio,
  selectedTicker,
  onTradeComplete,
}: TradeBarProps) {
  const { prices } = usePrices();
  const [ticker, setTicker] = useState('');
  const [quantity, setQuantity] = useState('');
  const [message, setMessage] = useState<TradeMessage | null>(null);
  const [loading, setLoading] = useState(false);

  // Sync ticker input with selected ticker
  useEffect(() => {
    if (selectedTicker) {
      setTicker(selectedTicker);
    }
  }, [selectedTicker]);

  const clearMessage = () => {
    setTimeout(() => setMessage(null), 3000);
  };

  const executeTrade = async (side: 'buy' | 'sell') => {
    const t = ticker.trim().toUpperCase();
    const q = parseFloat(quantity);

    if (!t) {
      setMessage({ type: 'error', text: 'Enter a ticker symbol' });
      clearMessage();
      return;
    }
    if (!q || q <= 0) {
      setMessage({ type: 'error', text: 'Enter a valid quantity' });
      clearMessage();
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || ''}/api/portfolio/trade`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: t, quantity: q, side }),
        }
      );

      const data = await res.json();

      if (data.success) {
        const price = data.trade?.price;
        setMessage({
          type: 'success',
          text: `${side === 'buy' ? 'Bought' : 'Sold'} ${q} ${t}${
            price ? ` @ $${price.toFixed(2)}` : ''
          }`,
        });
        setQuantity('');
        onTradeComplete();
      } else {
        setMessage({
          type: 'error',
          text: data.error || 'Trade failed',
        });
      }
    } catch {
      setMessage({ type: 'error', text: 'Network error. Try again.' });
    } finally {
      setLoading(false);
      clearMessage();
    }
  };

  const currentPrice = prices[ticker.toUpperCase()]?.price;
  const estimatedCost =
    currentPrice && quantity ? currentPrice * parseFloat(quantity) : null;

  return (
    <div className="flex flex-col gap-2 px-4 py-3 border-t border-[#30363d] bg-[#161b22]">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs text-[#8b949e] uppercase tracking-wider font-semibold min-w-fit">
          Trade
        </span>

        {/* Ticker input */}
        <div className="flex items-center gap-1">
          <label className="text-xs text-[#8b949e]">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs font-mono text-[#e6edf3] placeholder-[#8b949e] focus:outline-none focus:border-[#209dd7] w-20"
            maxLength={10}
          />
        </div>

        {/* Quantity input */}
        <div className="flex items-center gap-1">
          <label className="text-xs text-[#8b949e]">Qty</label>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="0"
            min="0.01"
            step="1"
            className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs font-mono text-[#e6edf3] placeholder-[#8b949e] focus:outline-none focus:border-[#209dd7] w-20"
          />
        </div>

        {/* Price estimate */}
        {estimatedCost && (
          <span className="text-xs text-[#8b949e] font-mono">
            ≈ ${estimatedCost.toFixed(2)}
          </span>
        )}

        {/* Cash balance */}
        {portfolio && (
          <span className="text-xs text-[#8b949e] font-mono ml-auto">
            Cash: ${portfolio.cash_balance.toFixed(2)}
          </span>
        )}

        {/* Trade buttons */}
        <button
          onClick={() => executeTrade('buy')}
          disabled={loading}
          className="bg-[#753991] hover:bg-[#8a44a8] text-white text-xs px-4 py-1.5 rounded font-semibold disabled:opacity-50 transition-colors"
        >
          BUY
        </button>
        <button
          onClick={() => executeTrade('sell')}
          disabled={loading}
          className="bg-[#f85149] hover:bg-[#e04340] text-white text-xs px-3 py-1.5 rounded font-semibold disabled:opacity-50 transition-colors"
        >
          SELL
        </button>
      </div>

      {/* Status message */}
      {message && (
        <div
          className={`text-xs px-2 py-1 rounded font-mono ${
            message.type === 'success'
              ? 'text-[#3fb950] bg-[#3fb950]/10'
              : 'text-[#f85149] bg-[#f85149]/10'
          }`}
        >
          {message.text}
        </div>
      )}
    </div>
  );
}
