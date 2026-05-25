# Market Data Interface — Design Reference

This document describes the unified Python interface for market data in FinAlly. All downstream code (SSE streaming, portfolio valuation, trade execution) is written against this interface and is agnostic to whether prices come from the simulator or the Massive API.

> **Note:** This document reflects the current implemented state. The definitive implementation blueprint (with full module code) is `MARKET_DATA_DESIGN.md`.

---

## Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  — GBM price simulation (no API key needed)
└── MassiveDataSource    — Polygon.io REST polling (MASSIVE_API_KEY required)
        │
        ▼  writes
   PriceCache (thread-safe, in-memory)
   ├── _prices:          dict[str, PriceUpdate]         latest price per ticker
   ├── _open_prices:     dict[str, float]               reference price (frozen at first update)
   ├── _history:         dict[str, deque[HistPoint]]    rolling 200-point buffer per ticker
   └── _ticker_versions: dict[str, int]                 per-ticker change counters for SSE diff
        │
        reads
        ├──→ SSE stream  GET /api/stream/prices
        ├──→ History     GET /api/prices/{ticker}/history
        ├──→ Portfolio valuation
        └──→ Trade execution
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
| `cache.py` | `PriceCache` | Thread-safe in-memory price store with history and versioning |
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
    open_price:     float   # Seed/reference price; set once on first cache update, never changed
    timestamp:      float   # Unix seconds (default: time.time())

    # Computed properties
    @property
    def change(self) -> float: ...              # price − previous_price, rounded to 4dp
    @property
    def change_percent(self) -> float: ...      # tick-to-tick % change, rounded to 4dp
    @property
    def daily_change_percent(self) -> float: .. # (price − open_price) / open_price × 100
    @property
    def direction(self) -> str: ...             # "up" | "down" | "flat"

    def to_sse_dict(self) -> dict: ...   # Exactly 5 fields for the SSE contract
    def to_dict(self) -> dict: ...       # All fields + computed props (portfolio/trade APIs)
```

`PriceUpdate` is immutable (`frozen=True, slots=True`). Every `cache.update()` call creates a new instance.

**`to_sse_dict()` output** (exactly 5 fields — direction and daily change % derived client-side):

```python
{
    "ticker":         "AAPL",
    "price":          191.25,
    "previous_price": 190.50,
    "open_price":     190.00,
    "timestamp":      1717435200.0,
}
```

**`to_dict()` output** (full serialisation for portfolio/trade APIs):

```python
{
    "ticker":               "AAPL",
    "price":                191.25,
    "previous_price":       190.50,
    "open_price":           190.00,
    "timestamp":            1717435200.0,
    "change":               0.75,
    "change_percent":       0.3937,
    "daily_change_percent": 0.6579,
    "direction":            "up",
}
```

---

## PriceCache

Thread-safe. A single background task (the data source) writes; multiple readers (SSE generator, portfolio routes, trade routes, history endpoint) read concurrently without external locking.

```python
class PriceCache:
    # Writer API
    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate
    def remove(self, ticker: str) -> None

    # Reader API
    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None          # Convenience
    def get_all(self) -> dict[str, PriceUpdate]               # Shallow copy
    def get_history(self, ticker: str) -> list[dict]          # [{price, timestamp}, ...] oldest first
    def get_ticker_versions(self) -> dict[str, int]           # Per-ticker change counters

    @property
    def version(self) -> int                                  # Global monotonic counter

    def __len__(self) -> int
    def __contains__(self, ticker: str) -> bool
```

**`update()` side-effects:**
- Sets `open_price` on first call for this ticker — never updated after that
- Appends `(price, timestamp)` to the ticker's 200-point history buffer
- Increments both the global `version` and the per-ticker version counter

**`remove()` side-effects:**
- Clears the ticker from all four internal dicts (`_prices`, `_open_prices`, `_history`, `_ticker_versions`)
- Increments the global `version` to signal SSE that the ticker list changed

**Per-ticker versions** allow the SSE generator to emit only tickers whose price changed since the last emission. This matters for Massive polling where most tickers are unchanged between 15-second polls.

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

1. `start(tickers)` — called once at application startup. Seeds the cache immediately before returning so SSE clients have prices from their very first connection.
2. `add_ticker(ticker)` / `remove_ticker(ticker)` — dynamic watchlist changes. Tickers are normalised with `.upper().strip()` by all implementations.
3. `stop()` — called at application shutdown. Cancels the background task. Idempotent.

`start()` must not be called twice on the same instance.

---

## Factory

```python
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
def create_stream_router(price_cache: PriceCache) -> APIRouter:
    ...  # Returns a fresh APIRouter with GET /api/stream/prices
```

**Behaviour:**
- Long-lived SSE connection via native `EventSource` API
- **Push-on-change**: emits only when at least one ticker's per-ticker version counter advances. Unchanged tickers are never re-sent.
- **Keepalive**: emits `: keepalive` every 10 seconds when no data event has been sent — prevents proxy timeouts during slow Massive poll cycles
- **Retry directive**: `retry: 1000\n\n` sent at connection start — EventSource reconnects in 1 second on disconnect
- **Disconnect detection**: polls `request.is_disconnected()` every 500ms

**Event format** (only changed tickers included):

```
data: {"AAPL": {"ticker": "AAPL", "price": 191.25, "previous_price": 190.50,
                "open_price": 190.00, "timestamp": 1717435200.0},
       "TSLA": {"ticker": "TSLA", "price": 251.80, "previous_price": 250.00,
                "open_price": 250.00, "timestamp": 1717435200.0}}

```

Frontend computes daily change %: `(price - open_price) / open_price * 100`.

---

## Application Wiring

```python
from app.market import PriceCache, create_market_data_source, create_stream_router

price_cache = PriceCache()
market_source = create_market_data_source(price_cache)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()                                          # DB must be ready first
    initial_tickers = await get_watchlist_tickers()         # Read from DB
    await market_source.start(initial_tickers)              # Seeds cache immediately
    app.include_router(create_stream_router(price_cache))
    yield
    await market_source.stop()
```

**Watchlist handlers** must call `add_ticker`/`remove_ticker` in the same request that modifies the database — there is no background reconciliation:

```python
# POST /api/watchlist
await market_source.add_ticker(ticker)

# DELETE /api/watchlist/{ticker}
await market_source.remove_ticker(ticker)
```

---

## Reading Prices (Downstream Code)

```python
# Single ticker
update: PriceUpdate | None = price_cache.get("AAPL")
price:  float | None        = price_cache.get_price("AAPL")

# All tickers (portfolio valuation)
all_prices: dict[str, PriceUpdate] = price_cache.get_all()
total_value = cash_balance + sum(
    pos.quantity * all_prices[pos.ticker].price
    for pos in positions
    if pos.ticker in all_prices
)

# Price history (chart endpoint)
history = price_cache.get_history("AAPL")
# → [{"price": 190.12, "timestamp": 1717435000.0}, ...]  up to 200 entries, oldest first
```

---

## Configuration Reference

```python
# Simulator — tune for demo feel
SimulatorDataSource(
    price_cache=cache,
    update_interval=0.5,       # seconds between ticks
    event_probability=0.001,   # probability of shock event per tick per ticker
)

# Massive — tune for plan tier
MassiveDataSource(
    api_key=key,
    price_cache=cache,
    poll_interval=15.0,   # Free tier: 5 req/min → 15s minimum
                          # Paid tiers: lower to 2–5s
)
```
