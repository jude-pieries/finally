'use client';

import { useState, useCallback, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

export function useWatchlist() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/watchlist`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { tickers: string[] } = await res.json();
      setTickers(data.tickers);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to fetch watchlist'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  const addTicker = useCallback(
    async (ticker: string): Promise<{ success: boolean; error?: string }> => {
      try {
        const res = await fetch(`${API_BASE}/api/watchlist`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: ticker.toUpperCase() }),
        });

        if (res.status === 409) {
          return { success: false, error: 'Ticker already in watchlist' };
        }

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          return {
            success: false,
            error: body.detail || `Error ${res.status}`,
          };
        }

        await fetchWatchlist();
        return { success: true };
      } catch (err) {
        return {
          success: false,
          error: err instanceof Error ? err.message : 'Network error',
        };
      }
    },
    [fetchWatchlist]
  );

  const removeTicker = useCallback(
    async (ticker: string): Promise<{ success: boolean; error?: string }> => {
      try {
        const res = await fetch(
          `${API_BASE}/api/watchlist/${encodeURIComponent(ticker)}`,
          { method: 'DELETE' }
        );

        if (!res.ok && res.status !== 404) {
          return { success: false, error: `Error ${res.status}` };
        }

        await fetchWatchlist();
        return { success: true };
      } catch (err) {
        return {
          success: false,
          error: err instanceof Error ? err.message : 'Network error',
        };
      }
    },
    [fetchWatchlist]
  );

  return { tickers, loading, error, fetchWatchlist, addTicker, removeTicker };
}
