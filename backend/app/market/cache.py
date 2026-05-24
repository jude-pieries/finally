"""Thread-safe in-memory price cache with history and per-ticker versioning."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache.

    Writers: one background task (SimulatorDataSource or MassiveDataSource).
    Readers: SSE generator, history endpoint, portfolio valuation, trade execution.
    """

    HISTORY_MAXLEN = 200

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._open_prices: dict[str, float] = {}                    # Set once on first update
        self._history: dict[str, deque[tuple[float, float]]] = {}   # (price, timestamp) pairs
        self._ticker_versions: dict[str, int] = {}                  # Per-ticker change counter
        self._version: int = 0
        self._lock = Lock()

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Sets open_price on the first call for this ticker — never updated after that.
        Appends to the ticker's rolling history buffer.
        Increments both the global and per-ticker version counters.
        """
        with self._lock:
            ts = timestamp or time.time()
            price = round(price, 2)

            if ticker not in self._open_prices:
                self._open_prices[ticker] = price
            open_price = self._open_prices[ticker]

            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=round(previous_price, 2),
                open_price=round(open_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update

            if ticker not in self._history:
                self._history[ticker] = deque(maxlen=self.HISTORY_MAXLEN)
            self._history[ticker].append((price, ts))

            self._version += 1
            self._ticker_versions[ticker] = self._ticker_versions.get(ticker, 0) + 1

            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        """Latest PriceUpdate for a ticker, or None if not yet seen."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Shallow copy — safe to iterate."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def get_history(self, ticker: str) -> list[dict]:
        """Rolling price history for a ticker (up to 200 points), oldest first.

        Returns a list of {"price": float, "timestamp": float} dicts.
        Empty list if the ticker is unknown or has no history.
        """
        with self._lock:
            hist = self._history.get(ticker)
            if not hist:
                return []
            return [{"price": p, "timestamp": t} for p, t in hist]

    def get_ticker_versions(self) -> dict[str, int]:
        """Per-ticker version counters. Used by the SSE generator to detect changes.

        Returns a shallow copy safe to compare against a previously captured snapshot.
        """
        with self._lock:
            return dict(self._ticker_versions)

    def remove(self, ticker: str) -> None:
        """Remove a ticker from all cache state."""
        with self._lock:
            self._prices.pop(ticker, None)
            self._open_prices.pop(ticker, None)
            self._history.pop(ticker, None)
            self._ticker_versions.pop(ticker, None)
            self._version += 1

    @property
    def version(self) -> int:
        """Global version counter. Bumped on every update and every remove."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
