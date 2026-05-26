'use client';

import { useState, useCallback } from 'react';
import { Header } from '@/components/Header';
import { WatchlistPanel } from '@/components/WatchlistPanel';
import { MainChart } from '@/components/MainChart';
import { PortfolioHeatmap } from '@/components/PortfolioHeatmap';
import { PnlChart } from '@/components/PnlChart';
import { PositionsTable } from '@/components/PositionsTable';
import { TradeBar } from '@/components/TradeBar';
import { ChatPanel } from '@/components/ChatPanel';
import { usePortfolio } from '@/hooks/usePortfolio';
import { useWatchlist } from '@/hooks/useWatchlist';

export default function TradingTerminal() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>('AAPL');
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const { portfolio, fetchPortfolio } = usePortfolio();
  const { fetchWatchlist } = useWatchlist();

  const handleTradeComplete = useCallback(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  const handleWatchlistChanged = useCallback(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  return (
    <div className="flex flex-col h-full bg-[#0d1117]">
      {/* Header */}
      <Header portfolio={portfolio} />

      {/* Main Layout */}
      <div className="flex flex-1 min-h-0">
        {/* Watchlist Panel */}
        <WatchlistPanel
          selectedTicker={selectedTicker}
          onSelectTicker={setSelectedTicker}
        />

        {/* Main Content Area */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0">
          {/* Top section: Main Chart */}
          <div className="flex-none h-[300px] border-b border-[#30363d] bg-[#0d1117]">
            <MainChart ticker={selectedTicker} />
          </div>

          {/* Middle section: Heatmap + P&L Chart */}
          <div className="flex flex-none h-[200px] border-b border-[#30363d]">
            {/* Portfolio Heatmap */}
            <div className="flex flex-col flex-1 min-w-0 border-r border-[#30363d]">
              <div className="px-3 py-1.5 border-b border-[#30363d]">
                <span className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">
                  Portfolio Heatmap
                </span>
              </div>
              <div className="flex-1 p-1">
                <PortfolioHeatmap portfolio={portfolio} />
              </div>
            </div>

            {/* P&L Chart */}
            <div className="flex flex-col w-[340px] min-w-[240px]">
              <PnlChart />
            </div>
          </div>

          {/* Positions Table — scrollable */}
          <div className="flex-1 overflow-y-auto min-h-0 border-b border-[#30363d]">
            <div className="px-3 py-2 border-b border-[#30363d] bg-[#161b22] sticky top-0 z-10">
              <span className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">
                Positions
              </span>
              {portfolio && (
                <span className="text-xs text-[#8b949e] ml-2">
                  ({portfolio.positions.length} open)
                </span>
              )}
            </div>
            <PositionsTable
              portfolio={portfolio}
              onTickerClick={setSelectedTicker}
            />
          </div>

          {/* Trade Bar */}
          <TradeBar
            portfolio={portfolio}
            selectedTicker={selectedTicker}
            onTradeComplete={handleTradeComplete}
          />
        </div>

        {/* Chat Panel */}
        <ChatPanel
          onTradeExecuted={handleTradeComplete}
          onWatchlistChanged={handleWatchlistChanged}
          isCollapsed={chatCollapsed}
          onToggle={() => setChatCollapsed(!chatCollapsed)}
        />
      </div>
    </div>
  );
}
