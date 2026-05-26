'use client';

import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
} from 'react';
import type { PriceData, ConnectionStatus } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

type SparklineMap = Record<string, number[]>;

type PriceContextValue = {
  prices: Record<string, PriceData>;
  connectionStatus: ConnectionStatus;
  sparklines: SparklineMap;
  flashState: Record<string, 'up' | 'down' | null>;
};

const PriceContext = createContext<PriceContextValue>({
  prices: {},
  connectionStatus: 'connecting',
  sparklines: {},
  flashState: {},
});

export function PriceProvider({ children }: { children: React.ReactNode }) {
  const [prices, setPrices] = useState<Record<string, PriceData>>({});
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>('connecting');
  const [sparklines, setSparklines] = useState<SparklineMap>({});
  const [flashState, setFlashState] = useState<
    Record<string, 'up' | 'down' | null>
  >({});
  const esRef = useRef<EventSource | null>(null);
  const flashTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const triggerFlash = useCallback(
    (ticker: string, direction: 'up' | 'down') => {
      // Clear any existing flash timer for this ticker
      if (flashTimers.current[ticker]) {
        clearTimeout(flashTimers.current[ticker]);
      }

      setFlashState((prev) => ({ ...prev, [ticker]: direction }));

      flashTimers.current[ticker] = setTimeout(() => {
        setFlashState((prev) => ({ ...prev, [ticker]: null }));
      }, 600);
    },
    []
  );

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (esRef.current) {
        esRef.current.close();
      }

      setConnectionStatus('connecting');
      const es = new EventSource(`${API_BASE}/api/stream/prices`);
      esRef.current = es;

      es.onopen = () => {
        setConnectionStatus('connected');
      };

      es.onmessage = (event) => {
        // Skip keepalive comments (those don't reach onmessage)
        if (!event.data || event.data.trim() === '') return;

        try {
          const batch = JSON.parse(event.data) as Record<string, PriceData>;

          setPrices((prev) => {
            const updated = { ...prev };
            for (const [ticker, data] of Object.entries(batch)) {
              updated[ticker] = data;
            }
            return updated;
          });

          // Update sparklines and trigger flashes
          setSparklines((prev) => {
            const updated = { ...prev };
            for (const [ticker, data] of Object.entries(batch)) {
              const existing = prev[ticker] || [];
              const next = [...existing, data.price].slice(-50);
              updated[ticker] = next;
            }
            return updated;
          });

          // Trigger flash for each updated ticker
          for (const [ticker, data] of Object.entries(batch)) {
            if (data.price !== data.previous_price) {
              triggerFlash(
                ticker,
                data.price > data.previous_price ? 'up' : 'down'
              );
            }
          }
        } catch {
          // Ignore parse errors (could be keepalive or malformed)
        }
      };

      es.onerror = () => {
        setConnectionStatus('disconnected');
        es.close();
        esRef.current = null;
        // EventSource has built-in retry, but we also manage reconnect manually
        reconnectTimer = setTimeout(() => {
          connect();
        }, 3000);
      };
    }

    connect();

    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      // Clear all flash timers
      for (const timer of Object.values(flashTimers.current)) {
        clearTimeout(timer);
      }
    };
  }, [triggerFlash]);

  return (
    <PriceContext.Provider
      value={{ prices, connectionStatus, sparklines, flashState }}
    >
      {children}
    </PriceContext.Provider>
  );
}

export function usePrices() {
  return useContext(PriceContext);
}
