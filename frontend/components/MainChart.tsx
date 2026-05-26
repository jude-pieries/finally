'use client';

import { useEffect, useRef, useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { usePrices } from '@/contexts/PriceContext';
import type { PricePoint } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

type ChartPoint = {
  time: string;
  price: number;
  timestamp: number;
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

type MainChartProps = {
  ticker: string | null;
};

export function MainChart({ ticker }: MainChartProps) {
  const { prices } = usePrices();
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const loadedTickerRef = useRef<string | null>(null);
  const accumulatedRef = useRef<ChartPoint[]>([]);

  // When ticker changes, fetch history
  useEffect(() => {
    if (!ticker) {
      setChartData([]);
      loadedTickerRef.current = null;
      accumulatedRef.current = [];
      return;
    }

    if (loadedTickerRef.current === ticker) return;
    loadedTickerRef.current = ticker;
    accumulatedRef.current = [];

    fetch(`${API_BASE}/api/prices/${encodeURIComponent(ticker)}/history`)
      .then((r) => r.json())
      .then((data: { ticker: string; history: PricePoint[] }) => {
        const points = data.history.map((p) => ({
          time: formatTime(p.timestamp),
          price: p.price,
          timestamp: p.timestamp,
        }));
        accumulatedRef.current = points;
        setChartData([...points]);
      })
      .catch(() => {
        // History unavailable, start fresh
        accumulatedRef.current = [];
        setChartData([]);
      });
  }, [ticker]);

  // Accumulate SSE updates for selected ticker
  useEffect(() => {
    if (!ticker) return;
    const priceData = prices[ticker];
    if (!priceData) return;

    const newPoint: ChartPoint = {
      time: formatTime(priceData.timestamp),
      price: priceData.price,
      timestamp: priceData.timestamp,
    };

    // Only add if this is actually a new timestamp
    const existing = accumulatedRef.current;
    if (
      existing.length === 0 ||
      existing[existing.length - 1].timestamp !== newPoint.timestamp
    ) {
      const updated = [...existing, newPoint].slice(-200);
      accumulatedRef.current = updated;
      setChartData([...updated]);
    }
  }, [ticker, prices]);

  if (!ticker) {
    return (
      <div className="flex items-center justify-center h-full text-[#8b949e] text-sm">
        Select a ticker from the watchlist to view chart
      </div>
    );
  }

  const priceData = prices[ticker];
  const currentPrice = priceData?.price;
  const openPrice = priceData?.open_price;
  const dailyChange =
    currentPrice && openPrice
      ? ((currentPrice - openPrice) / openPrice) * 100
      : null;

  // Y-axis domain with some padding
  const prices_ = chartData.map((d) => d.price);
  const minPrice = prices_.length ? Math.min(...prices_) : 0;
  const maxPrice = prices_.length ? Math.max(...prices_) : 100;
  const pad = (maxPrice - minPrice) * 0.05 || 1;
  const domain: [number, number] = [minPrice - pad, maxPrice + pad];

  return (
    <div className="flex flex-col h-full">
      {/* Chart header */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-[#30363d]">
        <span className="font-mono text-lg font-bold text-[#e6edf3]">
          {ticker}
        </span>
        {currentPrice && (
          <span className="font-mono text-xl text-[#209dd7] font-semibold">
            ${currentPrice.toFixed(2)}
          </span>
        )}
        {dailyChange !== null && (
          <span
            className={`font-mono text-sm ${
              dailyChange >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
            }`}
          >
            {dailyChange >= 0 ? '+' : ''}
            {dailyChange.toFixed(2)}% today
          </span>
        )}
        <span className="text-xs text-[#8b949e] ml-auto">
          {chartData.length} pts
        </span>
      </div>

      {/* Chart */}
      <div className="flex-1 p-2">
        {chartData.length < 2 ? (
          <div className="flex items-center justify-center h-full text-[#8b949e] text-sm">
            Waiting for price data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{ top: 5, right: 10, left: 10, bottom: 5 }}
            >
              <defs>
                <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#209dd7" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#209dd7" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#30363d"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                tick={{ fill: '#8b949e', fontSize: 10, fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={{ stroke: '#30363d' }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={domain}
                tick={{ fill: '#8b949e', fontSize: 10, fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `$${v.toFixed(2)}`}
                width={70}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1c2128',
                  border: '1px solid #30363d',
                  borderRadius: '4px',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                }}
                labelStyle={{ color: '#8b949e' }}
                itemStyle={{ color: '#209dd7' }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, 'Price']}
              />
              <Area
                type="monotone"
                dataKey="price"
                stroke="#209dd7"
                strokeWidth={1.5}
                fill="url(#priceGradient)"
                dot={false}
                activeDot={{ r: 3, fill: '#209dd7' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
