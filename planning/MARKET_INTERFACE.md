# Market Data Interface — Design Reference

This document describes the unified Python interface for market data in FinAlly. All downstream code (SSE streaming, portfolio valuation, trade execution) is written against this interface and is agnostic to whether prices come from the simulator or the Massive API.

---

## Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  — GBM price simulation (no API key needed)
└── MassiveDataSource    — Polygon.io REST polling (MASSIVE_API_KEY required)
        │
        ▼
   PriceCache (thread-safe, in-memory)
        │
        ├──▶ SSE stream  /api/stream/prices
        ├──▶ Portfolio valuation
        └──▶ Trade execution
```

**Strategy pattern.** Both sources implement the same `MarketDataSource` ABC. The `factory.py` module selects the correct implementation at startup based on the `MASSIVE_API_KEY` environment variable. No other code knows which source is active.

**PriceCache as the single point of truth.** The data source writes to the cache; everything else reads from it. There is no direct coupling between producers and consumers.

---

## Module Map

All modules live in `backend/app/market/`.

| File | Class / Export | Role |
|------|---------------|------|
| `models.py` | `PriceUpdate` | Immutable price snapshot dataclass |
| `interface.py` | `MarketDataSource` | Abstract base class |
| `cache.py` | `PriceCache` | Thread-safe in-memory price store |
| `simulator.py` | `SimulatorDataSource`, `GBMSimulator` | Simulation backend |
| `massive_client.py` | `MassiveDataSource` | Massive REST polling backend |
| `factory.py` | `create_market_data_source()` | Selects and constructs the active source |
| `stream.py` | `create_stream_router()` | FastAPI SSE endpoint factory |
| `seed_prices.py` | `SEED_PRICES`, `TICKER_PARAMS`, `CORRELATION_GROUPS` | Simulator configuration |

Public imports from the package root:

```python
from app.market import (
    PriceCache,
    PriceUpdate,
    MarketDataSource,
    create_market_data_source,
    create_stream_router,
)
```

---

## PriceUpdate

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker:         str
    price:          float
    previous_price: float
    timestamp:      float   # Unix seconds

    # Computed properties
    change:         float   # price - previous_price, rounded to 4dp
    change_percent: float   # % change, rounded to 4dp
    direction:      str     # "up" | "down" | "flat"

    def to_dict(self) -> dict: ...  # For JSON / SSE serialization
```

`PriceUpdate` is immutable (`frozen=True`). Every call to `cache.update()` creates a new instance — the previous update becomes `previous_price`.

`to_dict()` output:

```python
{
    "ticker":         "AAPL",
    "price":          191.25,
    "previous_price": 190.50,
    "timestamp":      1717435200.0,
    "change":         0.75,
    "change_percent": 0.3937,
    "direction":      "up",
}
```

---

## PriceCache

Thread-safe. A single writer (the data source background task) and multiple readers (SSE generator, portfolio routes, trade routes) can access the cache concurrently without external locking.

```python
class PriceCache:
    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate
    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None       # Convenience
    def get_all(self) -> dict[str, PriceUpdate]            # Shallow copy
    def remove(self, ticker: str) -> None

    @property
    def version(self) -> int   # Monotonic counter; bumped on every update
```

**Version counter.** The SSE generator tracks `price_cache.version` between polling intervals. When `version` changes, prices have updated and a new event should be emitted. This produces push-on-change semantics without subscribing to individual tickers.

First update for a ticker sets `previous_price == price` (direction `"flat"`). Subsequent updates carry the last known price as `previous_price`.

---

## MarketDataSource (ABC)

```python
class MarketDataSource(ABC):
    @abstractmethod
    async def start(self, tickers: list[str]) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None: ...

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None: ...

    @abstractmethod
    def get_tickers(self) -> list[str]: ...
```

**Lifecycle contract:**

1. `start(tickers)` — called once at application startup. Begins the background task and seeds the cache immediately so the SSE stream has data from the first client connection.
2. `add_ticker(ticker)` / `remove_ticker(ticker)` — dynamic watchlist changes. Take effect on the next poll cycle (Massive) or immediately (simulator, which also seeds the cache on `add_ticker`).
3. `stop()` — called at application shutdown. Cancels the background task. Safe to call multiple times.

`start()` must not be called twice on the same instance. `stop()` is idempotent.

---

## Factory

```python
# backend/app/market/factory.py

def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        return SimulatorDataSource(price_cache=price_cache)
```

The returned source is **unstarted**. Callers must `await source.start(tickers)`.

---

## SSE Stream

```python
# backend/app/market/stream.py

def create_stream_router(price_cache: PriceCache) -> APIRouter:
    ...
```

Returns a FastAPI `APIRouter` with one endpoint: `GET /api/stream/prices`.

**Behavior:**
- Long-lived SSE connection; client uses the native `EventSource` API
- Push-on-change: only emits when `price_cache.version` increments (i.e., when a price actually updates)
- Keepalive: sends `retry: 1000\n\n` at connection start; EventSource auto-reconnects in 1 second on disconnect
- Disconnect detection: polls `request.is_disconnected()` each 500ms interval

**Event format:**

```
data: {"AAPL": {"ticker": "AAPL", "price": 191.25, "previous_price": 190.50, ...}, "TSLA": {...}}

```

A single event carries all tracked tickers. The client merges this into its local price state.

---

## Application Wiring

```python
# FastAPI startup (pseudocode — adapt to your lifespan handler)
from app.market import PriceCache, create_market_data_source, create_stream_router

price_cache = PriceCache()
market_source = create_market_data_source(price_cache)

@asynccontextmanager
async def lifespan(app: FastAPI):
    initial_tickers = get_watchlist_from_db()
    await market_source.start(initial_tickers)
    app.include_router(create_stream_router(price_cache))
    yield
    await market_source.stop()
```

**Important:** the database must be initialized before `market_source.start()` is called, so `get_watchlist_from_db()` can read the seed tickers. This matches the decision in PLAN.md to initialize the database at startup-time.

---

## Watchlist Change Handlers

When the user adds or removes a ticker via the watchlist REST API:

```python
# POST /api/watchlist  → add ticker
await market_source.add_ticker(ticker)

# DELETE /api/watchlist/{ticker}  → remove ticker
await market_source.remove_ticker(ticker)
```

Both implementations handle these calls safely:
- **SimulatorDataSource:** updates the `GBMSimulator` immediately and seeds the cache so the new ticker has a price before the next SSE event.
- **MassiveDataSource:** adds/removes from the in-memory ticker list; the change takes effect on the next poll cycle (up to `poll_interval` seconds later).

---

## Reading Prices (Downstream Code)

```python
# Single ticker
update: PriceUpdate | None = price_cache.get("AAPL")
price:  float | None        = price_cache.get_price("AAPL")

# All tickers (e.g., for portfolio valuation)
all_prices: dict[str, PriceUpdate] = price_cache.get_all()
for ticker, update in all_prices.items():
    print(ticker, update.price, update.direction)
```

---

## Configuration Reference

### SimulatorDataSource

```python
SimulatorDataSource(
    price_cache:      PriceCache,
    update_interval:  float = 0.5,     # seconds between ticks
    event_probability: float = 0.001,  # chance of a shock event per tick per ticker
)
```

### MassiveDataSource

```python
MassiveDataSource(
    api_key:       str,
    price_cache:   PriceCache,
    poll_interval: float = 15.0,   # seconds between API calls (15s = safe for free tier)
)
```

For paid Massive plans, lower `poll_interval` to 2–5 seconds:

```python
MassiveDataSource(api_key=key, price_cache=cache, poll_interval=5.0)
```

---

## Extending the Interface

To add a new data source (e.g., Alpaca, Finnhub):

1. Create a new module in `backend/app/market/`.
2. Subclass `MarketDataSource` and implement all five abstract methods.
3. Update `factory.py` to select the new source based on an environment variable.
4. Write tests in `backend/tests/market/` following the patterns in `test_massive.py`.

No other code needs to change. The `PriceCache` interface is stable.
