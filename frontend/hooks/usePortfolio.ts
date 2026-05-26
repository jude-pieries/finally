'use client';

import { useState, useCallback, useEffect } from 'react';
import type { Portfolio, TradeRequest, TradeResponse } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/portfolio`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Portfolio = await res.json();
      setPortfolio(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch portfolio');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPortfolio();
    // Refresh portfolio every 30 seconds
    const interval = setInterval(fetchPortfolio, 30000);
    return () => clearInterval(interval);
  }, [fetchPortfolio]);

  const executeTrade = useCallback(
    async (trade: TradeRequest): Promise<TradeResponse> => {
      const res = await fetch(`${API_BASE}/api/portfolio/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(trade),
      });

      const data: TradeResponse = await res.json();

      if (data.success) {
        // Refresh portfolio after successful trade
        await fetchPortfolio();
      }

      return data;
    },
    [fetchPortfolio]
  );

  return { portfolio, loading, error, fetchPortfolio, executeTrade };
}
