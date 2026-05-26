'use client';

import { usePrices } from '@/contexts/PriceContext';
import type { Portfolio } from '@/types';

type HeaderProps = {
  portfolio: Portfolio | null;
};

export function Header({ portfolio }: HeaderProps) {
  const { connectionStatus } = usePrices();

  const statusColor =
    connectionStatus === 'connected'
      ? 'bg-[#3fb950]'
      : connectionStatus === 'connecting'
      ? 'bg-[#ecad0a]'
      : 'bg-[#f85149]';

  const statusLabel =
    connectionStatus === 'connected'
      ? 'Connected'
      : connectionStatus === 'connecting'
      ? 'Connecting...'
      : 'Disconnected';

  return (
    <header className="flex items-center justify-between h-12 px-4 bg-[#161b22] border-b border-[#30363d] flex-shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2">
        <span className="font-mono text-lg font-bold text-[#ecad0a] tracking-tight">
          Fin<span className="text-[#209dd7]">Ally</span>
        </span>
        <span className="text-xs text-[#8b949e] hidden sm:inline">
          AI Trading Workstation
        </span>
      </div>

      {/* Center: Portfolio Value */}
      <div className="flex items-center gap-6">
        {portfolio && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#8b949e] uppercase tracking-wider">
                Total
              </span>
              <span className="font-mono text-sm font-semibold text-[#e6edf3]">
                ${portfolio.total_value.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#8b949e] uppercase tracking-wider">
                Cash
              </span>
              <span className="font-mono text-sm text-[#8b949e]">
                ${portfolio.cash_balance.toFixed(2)}
              </span>
            </div>
            {/* P&L relative to $10k start */}
            {(() => {
              const pnl = portfolio.total_value - 10000;
              const pct = (pnl / 10000) * 100;
              return (
                <div className="flex items-center gap-1">
                  <span
                    className={`font-mono text-sm font-medium ${
                      pnl >= 0 ? 'text-[#3fb950]' : 'text-[#f85149]'
                    }`}
                  >
                    {pnl >= 0 ? '+' : ''}
                    {pnl.toFixed(2)} ({pct >= 0 ? '+' : ''}
                    {pct.toFixed(2)}%)
                  </span>
                </div>
              );
            })()}
          </>
        )}
      </div>

      {/* Right: Connection Status */}
      <div className="flex items-center gap-2">
        <div
          className={`w-2 h-2 rounded-full ${statusColor} ${
            connectionStatus === 'connecting' ? 'animate-pulse' : ''
          }`}
        />
        <span className="text-xs text-[#8b949e]">{statusLabel}</span>
      </div>
    </header>
  );
}
