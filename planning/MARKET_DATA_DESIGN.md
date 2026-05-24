# Market Data Backend — Implementation Design

This document is the definitive implementation blueprint for the market data subsystem. It synthesises `PLAN.md`, `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`, and the two comprehensive code reviews (`REVIEW.md`, `REVIEW_22:18:52:45.md`) into a single coherent design with complete, copy-pasteable code for every module.

All bugs and gaps identified in the reviews are resolved here:

| Review item | Resolution |
|---|---|
| `open_price` missing from `PriceUpdate` / `PriceCache` | Added as a field on `PriceUpdate`; `PriceCache` stores per-ticker open price on first update |
| SSE keepalive not implemented | 10-second `: keepalive` comment line added to `_generate_events` |
| Module-level `APIRouter` singleton in `stream.py` | Router created inside `create_stream_router()` on every call |
| Per-ticker push-on-change not implemented | `PriceCache` tracks per-ticker version counters; SSE generator diffs them |
| Rolling 200-point history buffer missing | `PriceCache` maintains `deque(maxlen=200)` per ticker; `get_history()` method added |
| `to_dict()` over-sends fields removed from SSE contract | Two serializers: `to_sse_dict()` (5 fields for SSE) and `to_dict()` (full, for portfolio API) |
| `version` property reads `_version` without lock | Lock acquired in the property |

---

## Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  — GBM price simulation, 500ms ticks (no API key needed)
└── MassiveDataSource    — Polygon.io REST batch snapshot, 15s poll (MASSIVE_API_KEY required)
        │
        ▼  writes
   PriceCache (thread-safe, in-memory)
   ├── _prices:          dict[str, PriceUpdate]         latest price per ticker
   ├── _open_prices:     dict[str, float]               reference/open price per ticker
   ├── _history:         dict[str, deque[HistPoint]]    rolling 200-point buffer per ticker
   └── _ticker_versions: dict[str, int]                 per-ticker change counter for SSE diff
        │
        reads
        ├── SSE stream  GET /api/stream/prices
        ├── History     GET /api/prices/{ticker}/history
        ├── Portfolio valuation
        └── Trade execution
```

**Strategy pattern.** Both sources implement `MarketDataSource`. The `factory.py` module picks the right one at startup. Downstream code is source-agnostic.

**PriceCache as single point of truth.** The data source writes; everything else reads. No direct coupling between producer and consumers.

---

## Module Map

All files live in `backend/app/market/`.

| File | Primary export(s) | Role |
|---|---|---|
| `models.py` | `PriceUpdate` | Immutable price snapshot with `open_price` |
| `cache.py` | `PriceCache` | Thread-safe store with history and per-ticker versioning |
| `interface.py` | `MarketDataSource` | Abstract base class |
| `seed_prices.py` | `SEED_PRICES`, `TICKER_PARAMS`, `CORRELATION_GROUPS` | Simulator configuration |
| `simulator.py` | `GBMSimulator`, `SimulatorDataSource` | GBM simulation backend |
| `massive_client.py` | `MassiveDataSource` | Massive REST polling backend |
| `factory.py` | `create_market_data_source()` | Selects source from env |
| `stream.py` | `create_stream_router()` | FastAPI SSE endpoint |
| `__init__.py` | Package re-exports | Clean public surface |

---

## 1. `models.py` — PriceUpdate

`PriceUpdate` is the unit of data that flows from cache to all consumers. It is frozen and slotted for efficiency.

Two serializers serve different consumers:

- `to_sse_dict()` — the exact 5 fields the SSE contract specifies (`ticker`, `price`, `previous_price`, `open_price`, `timestamp`). No derived fields — the frontend computes direction and daily change % itself.
- `to_dict()` — full serialization including computed properties, for portfolio and trade API responses.

```python
# backend/app/market/models.py
"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    open_price: float            # Simulator seed price or first Massive price; used for daily change %
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update (tick-to-tick)."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def daily_change_percent(self) -> float:
        """Percentage change from the open/reference price (daily change %)."""
        if self.open_price == 0:
            return 0.0
        return round((self.price - self.open_price) / self.open_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat' relative to the previous tick."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_sse_dict(self) -> dict:
        """Serialize for SSE transmission.

        Contains exactly the five fields in the SSE contract:
            ticker, price, previous_price, open_price, timestamp
        Direction and change % are derived client-side.
        """
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
        }

    def to_dict(self) -> dict:
        """Full serialization including computed fields.

        Used by portfolio and trade API responses where computed fields
        are convenient for the frontend.
        """
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "daily_change_percent": self.daily_change_percent,
            "direction": self.direction,
        }
```

---

## 2. `cache.py` — PriceCache

`PriceCache` is the hub of the market data subsystem. It stores the latest price per ticker, the reference open price (set on first update, never changed), a rolling 200-point history buffer per ticker, and a per-ticker version counter that enables the SSE generator to emit only changed tickers.

```python
# backend/app/market/cache.py
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

    Thread safety: all state is protected by a single Lock. The GIL alone is
    not sufficient on free-threaded CPython builds (PEP 703).
    """

    HISTORY_MAXLEN = 200  # Rolling buffer length per ticker

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._open_prices: dict[str, float] = {}                   # Set once on first update; never changed
        self._history: dict[str, deque[tuple[float, float]]] = {}  # (price, timestamp) pairs
        self._ticker_versions: dict[str, int] = {}                 # Per-ticker change counter
        self._version: int = 0                                      # Global change counter
        self._lock = Lock()

    # --- Writer API ---

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
    ) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Side effects:
          - Sets open_price on first call for this ticker (never updated after that).
          - Appends (price, timestamp) to the ticker's history buffer.
          - Increments both the global version and the per-ticker version.
        """
        with self._lock:
            ts = timestamp or time.time()
            price = round(price, 2)

            # Open price: set on first update, frozen thereafter
            if ticker not in self._open_prices:
                self._open_prices[ticker] = price
            open_price = self._open_prices[ticker]

            # Previous price: last known, or current on first update
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

            # History buffer
            if ticker not in self._history:
                self._history[ticker] = deque(maxlen=self.HISTORY_MAXLEN)
            self._history[ticker].append((price, ts))

            # Version counters
            self._version += 1
            self._ticker_versions[ticker] = self._ticker_versions.get(ticker, 0) + 1

            return update

    def remove(self, ticker: str) -> None:
        """Remove a ticker from all state (e.g., when removed from watchlist)."""
        with self._lock:
            self._prices.pop(ticker, None)
            self._open_prices.pop(ticker, None)
            self._history.pop(ticker, None)
            self._ticker_versions.pop(ticker, None)
            self._version += 1  # Signal SSE that the ticker list changed

    # --- Reader API ---

    def get(self, ticker: str) -> PriceUpdate | None:
        """Latest PriceUpdate for a ticker, or None if not yet seen."""
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Shallow copy — safe to iterate."""
        with self._lock:
            return dict(self._prices)

    def get_history(self, ticker: str) -> list[dict]:
        """Rolling price history for a ticker (up to 200 points).

        Returns a list of {"price": float, "timestamp": float} dicts,
        oldest first. Empty list if ticker is not tracked or has no history.
        """
        with self._lock:
            hist = self._history.get(ticker)
            if not hist:
                return []
            return [{"price": p, "timestamp": t} for p, t in hist]

    def get_ticker_versions(self) -> dict[str, int]:
        """Per-ticker version counters. Used by the SSE generator to detect changes.

        Returns a shallow copy — safe to compare against a previously captured snapshot.
        """
        with self._lock:
            return dict(self._ticker_versions)

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
```

### Why per-ticker versions?

The global `version` counter tells the SSE loop "something changed." The per-ticker counters tell it *which* tickers changed. This matters for Massive polling: in a single 15-second poll cycle only a subset of tickers may have moved. Without per-ticker tracking the SSE generator would re-emit all cached tickers on any change, triggering flash animations for tickers that did not actually move — violating the spec.

---

## 3. `interface.py` — MarketDataSource

The abstract contract all data source implementations must satisfy.

```python
# backend/app/market/interface.py
"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into PriceCache on their own schedule.
    Downstream code reads only from the cache — never from the source directly.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])   # called once at startup
        await source.add_ticker("TSLA")               # dynamic watchlist changes
        await source.remove_ticker("GOOGL")
        await source.stop()                           # called once at shutdown
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to PriceCache.
        Must be called exactly once. Calling start() twice is undefined.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Idempotent. After stop() the source will not write to the cache again.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        For SimulatorDataSource: takes effect immediately, seeds the cache.
        For MassiveDataSource: takes effect on the next poll cycle.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from PriceCache.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

---

## 4. `seed_prices.py` — Simulator Configuration

All simulator constants in one place. Edit this file to change starting prices or add new default tickers.

```python
# backend/app/market/seed_prices.py
"""Seed prices and per-ticker GBM parameters for the market simulator."""

# Realistic starting prices for the default 10-ticker watchlist.
# Tickers not in this dict receive a random price in [50.0, 300.0] on first encounter.
SEED_PRICES: dict[str, float] = {
    "AAPL":  190.00,
    "GOOGL": 175.00,
    "MSFT":  420.00,
    "AMZN":  185.00,
    "TSLA":  250.00,
    "NVDA":  800.00,
    "META":  500.00,
    "JPM":   195.00,
    "V":     280.00,
    "NFLX":  600.00,
}

# Per-ticker GBM parameters.
# sigma: annualised volatility (0.20 = 20%/yr; 0.50 = 50%/yr)
# mu:    annualised drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High vol, muted drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High vol, strong drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Stable bank
    "V":     {"sigma": 0.17, "mu": 0.04},  # Stable payments
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

# Fallback for tickers added at runtime that are not in TICKER_PARAMS.
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Sector groupings used to build the pairwise correlation matrix.
# Tickers in the same group have higher intra-group correlation.
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

# Correlation coefficients used by the Cholesky decomposition.
INTRA_TECH_CORR    = 0.6  # Same tech sector
INTRA_FINANCE_CORR = 0.5  # Same finance sector
CROSS_GROUP_CORR   = 0.3  # Between sectors, or unknown tickers
TSLA_CORR          = 0.3  # TSLA correlates weakly with everything (idiosyncratic)
```

---

## 5. `simulator.py` — GBM Simulator

### Mathematics

```
S(t + dt) = S(t) × exp((μ − ½σ²) × dt + σ × √dt × Z)
```

- `dt = 0.5 / 5,896,800 ≈ 8.48 × 10⁻⁸` (500ms as a fraction of a trading year)
- `Z` is drawn from a correlated multivariate normal via Cholesky decomposition
- Log-normal formulation guarantees prices are always positive

Correlated draws (Cholesky):
1. Draw `n` independent standard normals: `z ~ N(0,1)^n`
2. Apply lower-triangular Cholesky factor `L`: `z_corr = L @ z`
3. Use `z_corr[i]` as the `Z` for ticker `i`

`GBMSimulator` is a pure-Python computation class — no asyncio, no cache coupling. `SimulatorDataSource` wraps it with the asyncio background task and the `MarketDataSource` interface.

```python
# backend/app/market/simulator.py
"""GBM-based market simulator."""

from __future__ import annotations

import asyncio
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
    TICKER_PARAMS,
    TSLA_CORR,
)

logger = logging.getLogger(__name__)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)

    dt is expressed as a fraction of a trading year (252 days × 6.5 h × 3600 s).
    At 500ms per tick, dt ≈ 8.48e-8, producing sub-cent moves that accumulate
    naturally over a session.

    Correlation between tickers is modelled via a Cholesky decomposition of a
    pairwise correlation matrix built from sector groupings.
    """

    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR   # ≈ 8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability

        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    # --- Public API ---

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        Hot path — called every 500ms. Vectorised numpy operations for the
        correlated normal draws; Python loop only for shock events.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        z_independent = np.random.standard_normal(n)
        z_correlated = self._cholesky @ z_independent if self._cholesky is not None else z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            params = self._params[ticker]
            mu    = params["mu"]
            sigma = params["sigma"]

            drift     = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random shock event: ~0.1% chance per tick per ticker.
            # With 10 tickers at 2 ticks/sec: ~1 event every 50 seconds.
            if random.random() < self._event_prob:
                magnitude  = random.uniform(0.02, 0.05)
                shock_sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + magnitude * shock_sign
                logger.debug(
                    "Shock event on %s: %.1f%% %s",
                    ticker, magnitude * 100, "up" if shock_sign > 0 else "down",
                )

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the simulation. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker. Rebuilds the correlation matrix."""
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add without rebuilding Cholesky (for batch initialisation)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky factor of the ticker correlation matrix.

        O(n²) but n < 50. Called once at startup and on every add/remove.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Sector-based pairwise correlation.

        tech ↔ tech:     0.6
        finance ↔ finance: 0.5
        TSLA ↔ anything:  0.3  (idiosyncratic high-vol)
        cross-sector:     0.3
        """
        tech    = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]

        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by GBMSimulator.

    Runs an asyncio background task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to PriceCache.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)

        # Seed the cache immediately — SSE clients get prices from the very first connection.
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)

        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim is None:
            return
        self._sim.add_ticker(ticker)
        # Seed the cache immediately so the ticker appears in SSE before the next tick.
        price = self._sim.get_price(ticker)
        if price is not None:
            self._cache.update(ticker=ticker, price=price)
        logger.info("Simulator: added %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        """Core loop: step simulator → write cache → sleep 500ms."""
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

---

## 6. `massive_client.py` — Massive REST Polling

`MassiveDataSource` polls the Massive (Polygon.io) batch snapshot endpoint for all watched tickers in a single API call. The `RESTClient` is synchronous, so calls run in a thread via `asyncio.to_thread`.

Rate limits:
- Free tier: 5 req/min → poll every 15 s (default)
- Paid tiers: unlimited → lower `poll_interval` to 2–5 s

```python
# backend/app/market/massive_client.py
"""Massive (Polygon.io) REST polling client."""

from __future__ import annotations

import asyncio
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all watched
    tickers in a single API call, then writes results to PriceCache.

    The synchronous RESTClient is wrapped in asyncio.to_thread so it does
    not block the FastAPI event loop.
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._client: RESTClient | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)

        # Immediate first poll so the cache has data before the first SSE connection.
        await self._poll_once()

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval",
            len(tickers), self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added %s (takes effect on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Sleep then poll. First poll already done in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots, update cache."""
        if not self._tickers or not self._client:
            return

        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            updated = 0
            for snap in snapshots:
                try:
                    price     = snap.last_trade.price
                    timestamp = snap.last_trade.timestamp / 1000.0  # ms → seconds
                    self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                    updated += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s",
                        getattr(snap, "ticker", "???"), e,
                    )
            logger.debug("Massive poll: %d/%d tickers updated", updated, len(self._tickers))

        except Exception as e:
            # Non-fatal: 401 (bad key), 429 (rate limit), transient network errors.
            # The loop retries on the next interval.
            logger.error("Massive poll failed: %s", e)

    def _fetch_snapshots(self) -> list:
        """Synchronous Massive API call. Runs in a thread pool thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

---

## 7. `factory.py` — Source Selection

```python
# backend/app/market/factory.py
"""Factory: select the market data source based on environment variables."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Return the appropriate market data source.

    Selection logic:
      MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
      Otherwise                         → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)

    logger.info("Market data source: GBM Simulator")
    return SimulatorDataSource(price_cache=price_cache)
```

---

## 8. `stream.py` — SSE Streaming Endpoint

The SSE endpoint pushes price changes to connected browsers. Key design points:

- **Per-ticker push-on-change**: uses per-ticker version counters from `PriceCache` to emit only tickers whose price actually changed since the last SSE event. Stale tickers are never re-sent.
- **10-second keepalive**: a comment-only SSE line (`: keepalive`) is emitted if no data event has been sent in the last 10 seconds. This prevents proxy timeouts when Massive is polling slowly.
- **Fresh router per call**: `APIRouter` is created inside `create_stream_router()`, not at module level, so repeated calls (tests, hot reload) each get a clean router with no duplicate route registration.

```python
# backend/app/market/stream.py
"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 10.0  # seconds; emit ": keepalive" if no data sent in this window
_POLL_INTERVAL      = 0.5   # seconds; how often to check for cache changes


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Return a FastAPI APIRouter with the SSE /prices endpoint.

    Creates a fresh router on each call — safe to call from tests or after hot reload.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint for live price updates.

        Long-lived connection. Emits a JSON object only when at least one
        ticker's price has changed since the last emission. Between data events,
        emits a comment-only keepalive every 10 seconds to prevent proxy timeouts.

        Event format:
            data: {"AAPL": {"ticker": "AAPL", "price": 191.25, "previous_price": 190.50,
                            "open_price": 190.00, "timestamp": 1717435200.0}, ...}

        Only changed tickers are included in each event — unchanged tickers are omitted.
        """
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering for proxied deployments
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted events.

    Strategy:
      1. On each 500ms tick, compare current per-ticker version counters
         against the last-seen versions.
      2. Collect only tickers whose version advanced.
      3. If any changed, emit a data event containing only those tickers.
      4. If nothing changed and 10s has elapsed since the last emission,
         emit a comment keepalive.
      5. Stop when the client disconnects.
    """
    # Tell EventSource to reconnect after 1 second on disconnect.
    yield "retry: 1000\n\n"

    last_seen_versions: dict[str, int] = {}
    last_emit_at: float = time.monotonic()

    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            now = time.monotonic()
            current_versions = price_cache.get_ticker_versions()

            # Identify tickers that have a new price since we last emitted them.
            changed: dict[str, dict] = {}
            for ticker, version in current_versions.items():
                if version != last_seen_versions.get(ticker, -1):
                    update = price_cache.get(ticker)
                    if update is not None:
                        changed[ticker] = update.to_sse_dict()
                    last_seen_versions[ticker] = version

            # Prune last_seen for tickers that were removed from the cache.
            removed = set(last_seen_versions) - set(current_versions)
            for ticker in removed:
                del last_seen_versions[ticker]

            if changed:
                yield f"data: {json.dumps(changed)}\n\n"
                last_emit_at = now
            elif now - last_emit_at >= _KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_emit_at = now

            await asyncio.sleep(_POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
```

### SSE Event Format

A single event carries only the tickers that changed since the last event:

```
data: {"AAPL": {"ticker": "AAPL", "price": 191.25, "previous_price": 190.50,
                "open_price": 190.00, "timestamp": 1717435200.0},
       "TSLA": {"ticker": "TSLA", "price": 251.80, "previous_price": 250.00,
                "open_price": 250.00, "timestamp": 1717435200.0}}

```

Fields: exactly `ticker`, `price`, `previous_price`, `open_price`, `timestamp`.  
Daily change % is computed by the frontend: `(price - open_price) / open_price * 100`.

---

## 9. `__init__.py` — Package Exports

```python
# backend/app/market/__init__.py
"""Market data subsystem — public API."""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PriceCache",
    "PriceUpdate",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]
```

---

## 10. History Endpoint

The price history endpoint is backed by `PriceCache.get_history()`. It lives in the main FastAPI app (not in `app/market/`) but is documented here because its implementation depends on the cache design.

```python
# In backend/app/main.py (or a dedicated prices router)

from fastapi import APIRouter, HTTPException
from app.market import PriceCache

def create_prices_router(price_cache: PriceCache) -> APIRouter:
    router = APIRouter(prefix="/api/prices", tags=["prices"])

    @router.get("/{ticker}/history")
    async def get_price_history(ticker: str) -> dict:
        """Rolling price history for a single ticker.

        Returns the last 200 price points accumulated since the server started.
        Resets on container restart (in-memory only — acceptable for a demo).

        Response:
            {
                "ticker": "AAPL",
                "history": [
                    {"price": 190.12, "timestamp": 1717435000.0},
                    {"price": 190.25, "timestamp": 1717435000.5},
                    ...  up to 200 entries, oldest first
                ]
            }
        """
        ticker = ticker.upper().strip()
        history = price_cache.get_history(ticker)
        if not history:
            raise HTTPException(status_code=404, detail=f"No history for {ticker}")
        return {"ticker": ticker, "history": history}

    return router
```

---

## 11. Application Wiring

Full lifecycle integration with a FastAPI app.

```python
# backend/app/main.py
"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.db import init_db, get_watchlist_tickers   # database layer (separate module)

logger = logging.getLogger(__name__)

price_cache = PriceCache()
market_source = create_market_data_source(price_cache)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Database must be ready before market source starts so we can read the watchlist.
    await init_db()

    # 2. Load initial watchlist from DB.
    initial_tickers = await get_watchlist_tickers(user_id="default")
    logger.info("Initial watchlist: %s", initial_tickers)

    # 3. Start the market data source (seeds cache immediately before returning).
    await market_source.start(initial_tickers)

    # Yield control to FastAPI — application is now live.
    yield

    # Shutdown: stop the background task cleanly.
    await market_source.stop()


app = FastAPI(lifespan=lifespan)

# Market data routes
app.include_router(create_stream_router(price_cache))
app.include_router(create_prices_router(price_cache))

# Serve Next.js static export at the root
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

### Watchlist API Integration

When the watchlist REST endpoints add or remove a ticker, they must notify the market source:

```python
# In the watchlist router (wherever it lives)

from app.market import MarketDataSource

# POST /api/watchlist — add a ticker
async def add_to_watchlist(ticker: str, market_source: MarketDataSource):
    ticker = ticker.upper().strip()
    # ... validate, write to DB ...
    await market_source.add_ticker(ticker)    # Takes effect immediately (sim) or next poll (Massive)
    return {"ticker": ticker}


# DELETE /api/watchlist/{ticker} — remove a ticker
async def remove_from_watchlist(ticker: str, market_source: MarketDataSource):
    ticker = ticker.upper().strip()
    # ... remove from DB ...
    await market_source.remove_ticker(ticker)  # Also removes from PriceCache
    return {"ticker": ticker}
```

---

## 12. Downstream Price Reads

Portfolio valuation, trade execution, and the chat endpoint all read from the cache:

```python
from app.market import PriceCache, PriceUpdate

# Single ticker — returns None if not yet received
update: PriceUpdate | None = price_cache.get("AAPL")
price:  float | None        = price_cache.get_price("AAPL")

# All tickers — for portfolio valuation
all_prices: dict[str, PriceUpdate] = price_cache.get_all()

total_value = cash_balance
for position in positions:
    current = all_prices.get(position.ticker)
    if current:
        total_value += position.quantity * current.price

# Safe pattern for trade execution (price may be unknown if ticker just added)
def get_current_price_or_raise(ticker: str, cache: PriceCache) -> float:
    price = cache.get_price(ticker)
    if price is None:
        raise ValueError(f"No price data for {ticker} — try again in a moment")
    return price
```

---

## 13. Configuration Reference

### Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | (unset) | If set and non-empty, activates `MassiveDataSource`; otherwise uses simulator |

### Constructor Parameters

```python
# Simulator — tune for demo feel
SimulatorDataSource(
    price_cache=cache,
    update_interval=0.5,       # seconds between ticks (faster = more animation)
    event_probability=0.001,   # probability of shock event per tick per ticker
)

# Massive — tune for plan tier
MassiveDataSource(
    api_key=key,
    price_cache=cache,
    poll_interval=15.0,   # Free tier: 5 req/min → 15s safe minimum
                          # Starter/Advanced: lower to 2–5s
)
```

### Seed Price Tuning

Edit `seed_prices.py` to adjust starting prices or per-ticker volatility. Typical annualised volatility values for reference:

| Category | sigma range | Examples |
|---|---|---|
| Stable large-cap | 0.15–0.20 | JPM, V, KO |
| Standard tech | 0.20–0.30 | AAPL, MSFT, GOOGL |
| High-growth | 0.30–0.40 | META, NFLX, AMZN |
| High-volatility | 0.40–0.60 | TSLA, NVDA |

---

## 14. Testing Strategy

### Unit tests for `GBMSimulator`

```python
# backend/tests/market/test_simulator.py

def test_step_returns_all_tickers():
    sim = GBMSimulator(["AAPL", "TSLA"])
    result = sim.step()
    assert set(result.keys()) == {"AAPL", "TSLA"}

def test_prices_always_positive():
    sim = GBMSimulator(["AAPL"], event_probability=1.0)  # Force shock on every tick
    for _ in range(200):
        prices = sim.step()
        assert prices["AAPL"] > 0

def test_add_ticker_mid_session():
    sim = GBMSimulator(["AAPL"])
    sim.add_ticker("TSLA")
    assert "TSLA" in sim.get_tickers()
    prices = sim.step()
    assert "TSLA" in prices

def test_cholesky_rebuilt_on_add_remove():
    sim = GBMSimulator(["AAPL", "MSFT", "GOOGL"])
    sim.remove_ticker("MSFT")
    assert "MSFT" not in sim.get_tickers()
    # Should not raise — Cholesky was rebuilt for 2 tickers
    prices = sim.step()
    assert set(prices.keys()) == {"AAPL", "GOOGL"}
```

### Unit tests for `PriceCache`

```python
# backend/tests/market/test_cache.py

def test_open_price_set_on_first_update():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.5)  # Second update should not change open_price
    update = cache.get("AAPL")
    assert update.open_price == 190.0

def test_history_accumulates():
    cache = PriceCache()
    for i in range(5):
        cache.update("AAPL", 190.0 + i)
    history = cache.get_history("AAPL")
    assert len(history) == 5
    assert history[0]["price"] == 190.0
    assert history[-1]["price"] == 194.0

def test_history_capped_at_200():
    cache = PriceCache()
    for i in range(250):
        cache.update("AAPL", float(i))
    assert len(cache.get_history("AAPL")) == 200

def test_per_ticker_versions_increment():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    v1 = cache.get_ticker_versions()["AAPL"]
    cache.update("AAPL", 191.0)
    v2 = cache.get_ticker_versions()["AAPL"]
    assert v2 == v1 + 1

def test_per_ticker_versions_independent():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("TSLA", 250.0)
    cache.update("AAPL", 191.0)  # Only AAPL's version advances
    versions = cache.get_ticker_versions()
    assert versions["AAPL"] == 2
    assert versions["TSLA"] == 1

def test_remove_clears_all_state():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("AAPL")
    assert cache.get("AAPL") is None
    assert cache.get_history("AAPL") == []
    assert "AAPL" not in cache.get_ticker_versions()
```

### SSE endpoint tests

```python
# backend/tests/market/test_stream.py

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.market.cache import PriceCache
from app.market.stream import create_stream_router


@pytest.fixture
def app_with_stream():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    app = FastAPI()
    app.include_router(create_stream_router(cache))
    return app, cache


@pytest.mark.asyncio
async def test_sse_emits_initial_prices(app_with_stream):
    app, cache = app_with_stream
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/api/stream/prices") as response:
            assert response.status_code == 200
            # Read the retry directive
            line = await response.aiter_lines().__anext__()
            assert "retry" in line
            # Read the first data event
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    assert "AAPL" in payload
                    assert payload["AAPL"]["open_price"] == 190.0
                    break


@pytest.mark.asyncio
async def test_sse_only_sends_changed_tickers(app_with_stream):
    app, cache = app_with_stream
    cache.update("TSLA", 250.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", "/api/stream/prices") as response:
            # Consume initial events (both tickers)
            first_data = None
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    first_data = json.loads(line[5:].strip())
                    break

            # Now update only TSLA
            cache.update("TSLA", 255.0)

            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    second_data = json.loads(line[5:].strip())
                    # Only TSLA should appear — AAPL did not change
                    assert "TSLA" in second_data
                    assert "AAPL" not in second_data
                    break


@pytest.mark.asyncio
async def test_create_stream_router_returns_fresh_router():
    cache = PriceCache()
    router1 = create_stream_router(cache)
    router2 = create_stream_router(cache)
    assert router1 is not router2  # Each call returns a new router object
```

### Massive client tests

```python
# backend/tests/market/test_massive.py

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource


def make_snapshot(ticker: str, price: float, ts_ms: int = 1717435200000):
    snap = MagicMock()
    snap.ticker = ticker
    snap.last_trade.price = price
    snap.last_trade.timestamp = ts_ms
    return snap


@pytest.mark.asyncio
async def test_poll_once_updates_cache():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL", "TSLA"]

    with patch.object(source, "_fetch_snapshots", return_value=[
        make_snapshot("AAPL", 190.5),
        make_snapshot("TSLA", 251.0),
    ]):
        await source._poll_once()

    assert cache.get_price("AAPL") == 190.5
    assert cache.get_price("TSLA") == 251.0


@pytest.mark.asyncio
async def test_poll_once_skips_missing_last_trade():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL"]

    bad_snap = MagicMock()
    bad_snap.ticker = "AAPL"
    bad_snap.last_trade.price = None  # Missing trade data
    bad_snap.last_trade.timestamp = None

    with patch.object(source, "_fetch_snapshots", return_value=[bad_snap]):
        # Should not raise; bad snapshot is skipped with a warning
        await source._poll_once()

    assert cache.get_price("AAPL") is None


@pytest.mark.asyncio
async def test_poll_once_handles_api_error():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL"]

    with patch.object(source, "_fetch_snapshots", side_effect=Exception("429 rate limit")):
        # Should not raise — poll failures are logged and retried
        await source._poll_once()
```

---

## 15. Design Decision Summary

| Decision | Rationale |
|---|---|
| Strategy pattern (`MarketDataSource` ABC) | Downstream code is source-agnostic; adding a third source requires only a new subclass + factory update |
| `PriceCache` as single truth | Decouples producers from consumers; SSE, portfolio, and trade execution share the same data without coordination |
| `open_price` stored in cache, not in `PriceUpdate` constructor | Cache holds the reference price forever (set once on first update); every subsequent `PriceUpdate` carries it as a convenience field |
| Per-ticker version counters | Enables SSE to emit only tickers that actually changed — crucial for Massive polling where unchanged tickers should not trigger flash animations |
| Rolling 200-point deque in cache | History for the main chart, reset on restart — no DB schema needed for a demo; deque(maxlen=200) auto-evicts |
| `to_sse_dict()` vs `to_dict()` | SSE contract has exactly 5 fields; portfolio/trade APIs may want computed fields. Two serializers serve both cleanly |
| `APIRouter` created inside factory function | Prevents duplicate route registration when `create_stream_router` is called more than once (tests, hot reload) |
| SSE keepalive every 10s | Massive free tier polls every 15s; keepalive prevents proxy timeouts between polls |
| `asyncio.to_thread` for Massive client | `RESTClient` is synchronous; wrapping in a thread avoids blocking the FastAPI event loop |
| Simulator seeds cache on `add_ticker` | New watchlist additions appear in SSE on the next tick rather than waiting a full interval |
| GBM with Cholesky correlation | Log-normal prices (always positive), correlated sector moves, visually realistic — standard quantitative finance toolkit |
| Shock events (0.1% per tick) | Adds drama; prevents charts from looking flat during slow sessions |
