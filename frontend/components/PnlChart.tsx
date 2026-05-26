'use client';

import { useEffect, useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import type { PortfolioSnapshot } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

type ChartPoint = {
  time: string;
  value: number;
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function PnlChart() {
  const [data, setData] = useState<ChartPoint[]>([]);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/portfolio/history`);
        if (!res.ok) return;
        const json: { history: PortfolioSnapshot[] } = await res.json();
        const points = json.history.map((s) => ({
          time: formatTime(s.recorded_at),
          value: s.total_value,
        }));
        setData(points);
      } catch {
        // Silently fail
      }
    };

    fetchHistory();
    const interval = setInterval(fetchHistory, 30000);
    return () => clearInterval(interval);
  }, []);

  const values = data.map((d) => d.value);
  const minVal = values.length ? Math.min(...values) : 9000;
  const maxVal = values.length ? Math.max(...values) : 11000;
  const pad = (maxVal - minVal) * 0.1 || 100;
  const domain: [number, number] = [minVal - pad, maxVal + pad];

  const latestValue = data[data.length - 1]?.value;
  const pnl = latestValue ? latestValue - 10000 : null;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-[#30363d]">
        <span className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">
          Portfolio P&L
        </span>
        {pnl !== null && (
          <span
            className={`font-mono text-sm font-medium ${
              pnl >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
            }`}
          >
            {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
          </span>
        )}
      </div>
      <div className="flex-1 p-1">
        {data.length < 2 ? (
          <div className="flex items-center justify-center h-full text-[#8b949e] text-xs">
            Collecting data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={data}
              margin={{ top: 5, right: 5, left: 5, bottom: 5 }}
            >
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#209dd7" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#209dd7" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="2 2"
                stroke="#30363d"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                tick={{
                  fill: '#8b949e',
                  fontSize: 9,
                  fontFamily: 'monospace',
                }}
                tickLine={false}
                axisLine={{ stroke: '#30363d' }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={domain}
                tick={{
                  fill: '#8b949e',
                  fontSize: 9,
                  fontFamily: 'monospace',
                }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => `$${v.toFixed(0)}`}
                width={60}
              />
              <ReferenceLine
                y={10000}
                stroke="#8b949e"
                strokeDasharray="4 4"
                strokeOpacity={0.5}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1c2128',
                  border: '1px solid #30363d',
                  borderRadius: '4px',
                  fontFamily: 'monospace',
                  fontSize: '11px',
                }}
                labelStyle={{ color: '#8b949e' }}
                itemStyle={{ color: '#209dd7' }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, 'Value']}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#209dd7"
                strokeWidth={1.5}
                fill="url(#pnlGradient)"
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
