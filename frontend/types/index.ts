// Market Data Types
export type PriceData = {
  ticker: string;
  price: number;
  previous_price: number;
  open_price: number;
  timestamp: number;
};

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

// Portfolio Types
export type Position = {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  value: number;
  unrealized_pnl: number;
  pnl_percent: number;
  daily_change_percent: number;
};

export type Portfolio = {
  cash_balance: number;
  total_value: number;
  positions: Position[];
};

// Portfolio History
export type PortfolioSnapshot = {
  total_value: number;
  recorded_at: string;
};

export type PortfolioHistory = {
  history: PortfolioSnapshot[];
};

// Trade Types
export type TradeSide = 'buy' | 'sell';

export type TradeRequest = {
  ticker: string;
  quantity: number;
  side: TradeSide;
};

export type TradeResult = {
  ticker: string;
  side: TradeSide;
  quantity: number;
  price: number;
};

export type TradeResponse = {
  success: boolean;
  error: string | null;
  cash_balance: number;
  trade: TradeResult;
};

// Watchlist Types
export type WatchlistResponse = {
  tickers: string[];
};

// Ticker Price History
export type PricePoint = {
  price: number;
  timestamp: number;
};

export type TickerHistory = {
  ticker: string;
  history: PricePoint[];
};

// Chat Types
export type ChatTrade = {
  ticker: string;
  side: TradeSide;
  quantity: number;
};

export type WatchlistChange = {
  ticker: string;
  action: 'add' | 'remove';
};

export type ChatResponse = {
  message: string;
  trades: ChatTrade[];
  watchlist_changes: WatchlistChange[];
  errors: string[];
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  trades?: ChatTrade[];
  watchlist_changes?: WatchlistChange[];
  errors?: string[];
  timestamp: number;
};

// Health Check
export type HealthResponse = {
  status: string;
  market_data: 'simulator' | 'massive';
  tickers: number;
};
