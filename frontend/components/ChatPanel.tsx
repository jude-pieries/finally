'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage, ChatResponse } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

type ChatPanelProps = {
  onTradeExecuted?: () => void;
  onWatchlistChanged?: () => void;
  isCollapsed: boolean;
  onToggle: () => void;
};

export function ChatPanel({
  onTradeExecuted,
  onWatchlistChanged,
  isCollapsed,
  onToggle,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data: ChatResponse = await res.json();

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: data.message,
        trades: data.trades,
        watchlist_changes: data.watchlist_changes,
        errors: data.errors,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // Trigger portfolio refresh if trades were executed
      if (data.trades && data.trades.length > 0) {
        onTradeExecuted?.();
      }

      // Trigger watchlist refresh if changes were made
      if (data.watchlist_changes && data.watchlist_changes.length > 0) {
        onWatchlistChanged?.();
      }
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        errors: [err instanceof Error ? err.message : 'Unknown error'],
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, onTradeExecuted, onWatchlistChanged]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (isCollapsed) {
    return (
      <div className="flex flex-col items-center bg-[#161b22] border-l border-[#30363d] w-10">
        <button
          onClick={onToggle}
          className="p-2 text-[#8b949e] hover:text-[#e6edf3] transition-colors mt-2"
          title="Open AI Chat"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z"
              clipRule="evenodd"
            />
          </svg>
        </button>
        {messages.length > 0 && (
          <div className="w-2 h-2 rounded-full bg-[#ecad0a] mt-1" />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col bg-[#161b22] border-l border-[#30363d] w-80 min-w-80">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#30363d]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#ecad0a] uppercase tracking-wider">
            AI Assistant
          </span>
          <span className="text-xs text-[#8b949e]">FinAlly</span>
        </div>
        <button
          onClick={onToggle}
          className="text-[#8b949e] hover:text-[#e6edf3] transition-colors text-lg leading-none"
          title="Collapse chat"
        >
          ›
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="text-center text-xs text-[#8b949e] mt-8">
            <div className="text-[#ecad0a] text-2xl mb-2">✦</div>
            <p className="font-medium text-[#e6edf3] mb-1">
              Hi, I&apos;m FinAlly!
            </p>
            <p className="text-[#8b949e]">
              Ask me to analyze your portfolio, suggest trades, or execute
              buy/sell orders.
            </p>
            <div className="mt-4 space-y-1 text-left">
              <p className="text-xs text-[#8b949e] italic">Try asking:</p>
              {[
                '"How is my portfolio doing?"',
                '"Buy 5 shares of AAPL"',
                '"Add PYPL to my watchlist"',
                '"What should I sell?"',
              ].map((hint) => (
                <button
                  key={hint}
                  onClick={() => setInput(hint.replace(/"/g, ''))}
                  className="block w-full text-left text-xs text-[#209dd7] hover:text-[#e6edf3] py-0.5 transition-colors"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-xs ${
                msg.role === 'user'
                  ? 'bg-[#753991] text-white'
                  : 'bg-[#1c2128] text-[#e6edf3]'
              }`}
            >
              <p className="whitespace-pre-wrap leading-relaxed">
                {msg.content}
              </p>

              {/* Executed trades */}
              {msg.trades && msg.trades.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-[#30363d] pt-2">
                  {msg.trades.map((t, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-1 text-[#3fb950] font-mono text-xs"
                    >
                      <span>✓</span>
                      <span>
                        {t.side === 'buy' ? 'Bought' : 'Sold'} {t.quantity}{' '}
                        {t.ticker}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Watchlist changes */}
              {msg.watchlist_changes && msg.watchlist_changes.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-[#30363d] pt-2">
                  {msg.watchlist_changes.map((w, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-1 text-[#209dd7] font-mono text-xs"
                    >
                      <span>{w.action === 'add' ? '+' : '−'}</span>
                      <span>
                        {w.action === 'add' ? 'Added' : 'Removed'} {w.ticker}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Errors */}
              {msg.errors && msg.errors.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-[#30363d] pt-2">
                  {msg.errors.map((err, i) => (
                    <p key={i} className="text-[#f85149] text-xs">
                      ⚠ {err}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-[#1c2128] rounded-lg px-3 py-2">
              <div className="flex gap-1 items-center">
                <div className="w-1.5 h-1.5 rounded-full bg-[#8b949e] animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-[#8b949e] animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-[#8b949e] animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[#30363d] p-3">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask FinAlly..."
            rows={2}
            className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-2 py-1.5 text-xs text-[#e6edf3] placeholder-[#8b949e] focus:outline-none focus:border-[#209dd7] resize-none font-sans leading-relaxed"
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="bg-[#753991] hover:bg-[#8a44a8] text-white text-xs px-3 py-1.5 rounded font-semibold disabled:opacity-50 transition-colors self-end"
          >
            Send
          </button>
        </div>
        <p className="text-xs text-[#8b949e] mt-1">
          Press Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}
