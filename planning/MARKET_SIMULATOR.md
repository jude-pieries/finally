# Market Simulator — Design Reference

This document describes the GBM-based market simulator used by FinAlly when no `MASSIVE_API_KEY` is set. It covers the mathematics, code structure, configuration, and the behaviours that make simulated data visually compelling.

---

## Overview

The simulator generates realistic-looking stock price movements using **Geometric Brownian Motion (GBM)** — the same model underlying the Black-Scholes options pricing formula. Prices tick every 500ms, move in correlated groups (tech stocks move together, finance stocks move together), and occasionally experience sudden shock events for visual drama.

No external dependencies beyond `numpy`. No network calls. Zero latency.

---

## Mathematical Model

### GBM Equation

```
S(t + dt) = S(t) × exp((μ - ½σ²) × dt + σ × √dt × Z)
```

Where:

| Symbol | Meaning |
|--------|---------|
| `S(t)` | Current price |
| `μ` (mu) | Annualised drift (expected return) |
| `σ` (sigma) | Annualised volatility |
| `dt` | Time step as a fraction of a trading year |
| `Z` | Standard normal random variable |

### Time Step

```python
TRADING_SECONDS_PER_YEAR = 252 × 6.5 × 3600 = 5,896,800
DEFAULT_DT = 0.5 / 5,896,800  # ≈ 8.48 × 10⁻⁸
```

A 500ms tick represents a tiny fraction of a trading year. This produces sub-cent moves per tick that accumulate naturally over time — matching the visual feel of a real trading terminal.

### Why the Log-Normal Form?

The `exp(...)` formulation guarantees prices are always positive (they can asymptotically approach zero but never go negative). It also ensures that percentage moves are symmetric in log-space, matching the empirical observation that large stocks move ~2% up or down with roughly equal frequency.

---

## Correlated Moves

In real markets, stocks in the same sector tend to move together. The simulator models this with a **Cholesky decomposition** of a pairwise correlation matrix.

### Correlation Groups

```python
CORRELATION_GROUPS = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR    = 0.6   # Same tech sector
INTRA_FINANCE_CORR = 0.5   # Same finance sector
CROSS_GROUP_CORR   = 0.3   # Cross-sector or unknown
TSLA_CORR          = 0.3   # TSLA treated as independent (high idiosyncratic vol)
```

### Cholesky Algorithm

Each tick:

1. Generate `n` independent standard normal draws: `z_independent = N(0,1)^n`
2. Apply the Cholesky factor `L` (lower triangular): `z_correlated = L @ z_independent`
3. Use `z_correlated[i]` as the `Z` term in each ticker's GBM equation

`L` is computed once at startup and rebuilt whenever a ticker is added or removed. With `n < 50`, this is O(n²) and fast.

```python
corr = np.eye(n)                # Start with identity
for i, j in upper_triangle:
    corr[i, j] = corr[j, i] = pairwise_correlation(tickers[i], tickers[j])

L = np.linalg.cholesky(corr)   # Lower triangular Cholesky factor
```

### Effect

A tech sector shock in the random draws propagates to all tech tickers simultaneously, creating the kind of correlated volatility clusters visible in real data. Cross-sector moves are weakly correlated, and TSLA has its own idiosyncratic component.

---

## Shock Events

Beyond continuous GBM moves, ~0.1% of ticks trigger a sudden price shock:

```python
if random.random() < 0.001:                   # 0.1% probability
    magnitude = random.uniform(0.02, 0.05)    # 2–5% move
    direction = random.choice([-1, 1])
    price *= 1 + magnitude * direction
```

With 10 tickers updating at 2 Hz, a shock event fires roughly every 50 seconds. This creates the brief, dramatic price swings visible in real markets (earnings surprises, news events) and makes the watchlist price-flash animations look alive.

---

## Code Structure

### `GBMSimulator`

Pure simulation logic. Knows nothing about FastAPI, asyncio, or the cache.

```python
class GBMSimulator:
    def __init__(self, tickers: list[str], dt: float, event_probability: float)

    def step(self) -> dict[str, float]          # Advance all tickers one tick
    def add_ticker(self, ticker: str) -> None   # Add; rebuilds Cholesky
    def remove_ticker(self, ticker: str) -> None
    def get_price(self, ticker: str) -> float | None
    def get_tickers(self) -> list[str]
```

`step()` is the hot path. Called every 500ms. It runs the full Cholesky correlation + GBM for all tracked tickers in a single numpy vectorised operation, then applies shock events in a Python loop. Returns `{ticker: price}`.

### `SimulatorDataSource`

Adapts `GBMSimulator` to the `MarketDataSource` interface. Owns the asyncio background task.

```python
class SimulatorDataSource(MarketDataSource):
    async def start(self, tickers: list[str]) -> None
    async def stop(self) -> None
    async def add_ticker(self, ticker: str) -> None
    async def remove_ticker(self, ticker: str) -> None
    def get_tickers(self) -> list[str]

    async def _run_loop(self) -> None   # Core loop: step → write cache → sleep
```

**Startup sequence in `start()`:**

1. Instantiate `GBMSimulator` with initial tickers
2. Seed the `PriceCache` immediately with initial prices — so SSE has data from the first client connection, before the first tick fires
3. Launch `_run_loop()` as an asyncio background task

**`_run_loop()` pseudocode:**

```
loop:
    prices = simulator.step()
    for ticker, price in prices:
        cache.update(ticker, price)
    await asyncio.sleep(0.5)
```

The loop runs until cancelled. Exceptions from `step()` are caught and logged so a transient numpy error doesn't kill the entire server.

### `add_ticker()` behaviour

When the user adds a new ticker to their watchlist mid-session:

1. `GBMSimulator.add_ticker()` assigns a seed price (from `SEED_PRICES` if known, else random in $50–$300) and rebuilds the Cholesky matrix
2. `SimulatorDataSource.add_ticker()` immediately seeds the cache with the initial price so the ticker appears in the SSE stream at the next tick, not one full interval later

---

## Seed Configuration (`seed_prices.py`)

All simulator constants live in `backend/app/market/seed_prices.py`. This is the single file to edit when adjusting starting prices or adding new tickers.

### Seed Prices

Realistic starting prices for the default 10 tickers:

```python
SEED_PRICES = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V":    280.00,
    "NFLX": 600.00,
}
```

Tickers not in this dict get a random price in `[50.0, 300.0]`.

### Per-Ticker GBM Parameters

```python
TICKER_PARAMS = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High vol, lower drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High vol, strong drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Low vol (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},  # Low vol (payments)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

DEFAULT_PARAMS = {"sigma": 0.25, "mu": 0.05}  # Fallback for unknown tickers
```

`sigma` is annualised volatility. Typical real-world values:
- Stable large-cap (JPM, V): 0.15–0.20
- Standard tech (AAPL, MSFT): 0.20–0.30
- High-growth / volatile (TSLA, NVDA): 0.40–0.60

`mu` is annualised drift (expected return). All tickers set near 0.05 (5% per year) to prevent prices drifting to zero or infinity during a long demo session.

---

## Instantiation Example

```python
from app.market.simulator import GBMSimulator

sim = GBMSimulator(
    tickers=["AAPL", "TSLA", "NVDA"],
    dt=GBMSimulator.DEFAULT_DT,       # 500ms / trading year
    event_probability=0.001,
)

# Manually step 5 ticks
for _ in range(5):
    prices = sim.step()
    print(prices)
    # {"AAPL": 190.12, "TSLA": 250.87, "NVDA": 801.44}

# Add a ticker mid-session
sim.add_ticker("MSFT")
prices = sim.step()  # All 4 tickers now included
```

---

## Full Integration Example

```python
import asyncio
from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource

async def main():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=0.5)

    await source.start(["AAPL", "TSLA", "NVDA"])

    # Read prices after a couple of ticks
    await asyncio.sleep(2.0)
    for ticker, update in cache.get_all().items():
        print(f"{ticker}: ${update.price:.2f}  {update.direction}")

    # Add a new ticker
    await source.add_ticker("MSFT")
    await asyncio.sleep(1.0)
    print(cache.get("MSFT"))

    await source.stop()

asyncio.run(main())
```

---

## Demo

A Rich terminal dashboard is available for visually inspecting the simulator:

```bash
cd backend
uv run market_data_demo.py
```

Displays 10 tickers with live-updating prices, sparklines, colour-coded direction arrows, and a shock event log. Runs for 60 seconds or until Ctrl-C.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| GBM over random walk | Log-normal distribution; prices can't go negative; realistic percentage volatility |
| Cholesky correlation | Captures sector co-movement cheaply; O(n²) matrix rebuild is fine for n < 50 |
| Shock events | Adds drama; prevents flat-looking charts during slow sessions |
| 500ms tick | Fast enough to look live; slow enough that the browser SSE stream never floods |
| Seed prices in a separate file | Single place to edit starting conditions; agents don't need to touch simulator logic |
| `GBMSimulator` decoupled from asyncio | Pure computation class is easy to test; `SimulatorDataSource` owns the concurrency |
| Immediate cache seeding on `add_ticker` | New tickers appear in the SSE stream on the next event, not one full tick later |
