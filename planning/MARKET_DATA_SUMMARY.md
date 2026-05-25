# Market Data Backend — Summary

**Status:** Complete, reviewed, all issues resolved. Ready for downstream integration.

## What Was Built

A complete market data subsystem in `backend/app/market/` — 8 modules, ~400 LOC — providing live price simulation and real market data via a unified interface.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Polygon.io REST poller (when MASSIVE_API_KEY set)
        │
        ▼  writes
   PriceCache (thread-safe, in-memory)
   ├── _prices:          latest PriceUpdate per ticker
   ├── _open_prices:     reference/open price per ticker (frozen at first update)
   ├── _history:         rolling 200-point buffer per ticker (for chart endpoint)
   └── _ticker_versions: per-ticker change counters (for SSE push-on-change)
        │
        reads
        ├──→ SSE stream endpoint  GET /api/stream/prices
        ├──→ History endpoint     GET /api/prices/{ticker}/history
        ├──→ Portfolio valuation
        └──→ Trade execution
```

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PriceUpdate` — immutable frozen dataclass: `ticker`, `price`, `previous_price`, `open_price`, `timestamp`; computed properties `change`, `change_percent`, `daily_change_percent`, `direction`; `to_sse_dict()` (5-field SSE payload) and `to_dict()` (full serialisation) |
| `interface.py` | `MarketDataSource` — abstract base class: `start`, `stop`, `add_ticker`, `remove_ticker`, `get_tickers` |
| `cache.py` | `PriceCache` — thread-safe store; `update()`, `get()`, `get_all()`, `get_price()`, `get_history()`, `get_ticker_versions()`, `remove()`; global and per-ticker version counters |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params (drift/volatility), sector correlation groups |
| `simulator.py` | `GBMSimulator` — GBM with Cholesky-correlated moves, shock events; `SimulatorDataSource` — asyncio background task wrapping the simulator |
| `massive_client.py` | `MassiveDataSource` — Polygon.io batch snapshot polling, `asyncio.to_thread` for sync client, ticker normalisation |
| `factory.py` | `create_market_data_source()` — selects simulator or Massive based on `MASSIVE_API_KEY` env var |
| `stream.py` | `create_stream_router()` — FastAPI SSE router factory; push-on-change via per-ticker version diffing; 10s keepalive |

### Key Design Decisions

| Decision | Rationale |
|---|---|
| Strategy pattern (MarketDataSource ABC) | Downstream code is source-agnostic; adding a third source requires only a new subclass + factory update |
| PriceCache as single point of truth | Producers write, consumers read — no direct coupling between simulator/Massive and SSE/portfolio/trade |
| `open_price` frozen at first update | Provides a stable daily change % reference throughout a session; consistent between simulator and Massive |
| Per-ticker version counters | SSE emits only tickers whose price actually changed — critical for Massive polling where most tickers are unchanged between polls |
| 200-point rolling history deque | Serves the main chart endpoint; resets on restart (acceptable for a demo); no DB schema needed |
| `to_sse_dict()` vs `to_dict()` | SSE contract specifies exactly 5 fields; portfolio/trade APIs can use computed properties — two serialisers serve both without over-sending |
| Router created inside factory function | Prevents duplicate route registration across test runs and hot reloads |
| SSE keepalive every 10s | Prevents proxy timeouts during slow Massive poll intervals |
| GBM with Cholesky correlation | Log-normal prices (always positive), correlated sector moves, visually realistic |
| Shock events (0.1% per tick) | Adds drama; prevents charts from looking flat during slow sessions |

---

## Test Suite

**100 tests, all passing. 97% overall coverage.** 7 test modules in `backend/tests/market/`.

```
uv run --extra dev pytest tests/market/ -v
uv run --extra dev pytest tests/market/ --cov=app/market
```

| Module | Tests | Key coverage |
|--------|-------|---|
| `test_models.py` | 16 | `models.py`: 100% |
| `test_cache.py` | 26 | `cache.py`: 100% |
| `test_simulator.py` | 19 | `simulator.py`: 96% |
| `test_simulator_source.py` | 10 | Integration: start/stop/add/remove lifecycle |
| `test_factory.py` | 7 | `factory.py`: 100% |
| `test_massive.py` | 13 | `massive_client.py`: 94% |
| `test_stream.py` | 9 | `stream.py`: 96% |

Lint: `uv run --extra dev ruff check app/market/ tests/market/` — **no issues**.

---

## Review History

Two comprehensive code reviews were carried out. All findings were resolved.

**Review 1** — identified 7 issues, all fixed:
1. `open_price` missing from `PriceUpdate` and `PriceCache` → added as a first-class field
2. SSE keepalive not implemented → 10s `: keepalive` comment added
3. Module-level `APIRouter` singleton → router created inside `create_stream_router()` on every call
4. Per-ticker push-on-change not implemented → `PriceCache` per-ticker version counters + SSE diffing
5. Rolling history buffer missing → `deque(maxlen=200)` per ticker; `get_history()` method added
6. `version` property read without lock → lock acquired in property
7. `to_dict()` over-sent fields → two serialisers: `to_sse_dict()` and `to_dict()`

**Review 2** — identified 3 issues, all fixed:
1. `test_stream.py` unsorted import block → fixed with `ruff --fix`
2. `MassiveDataSource.start()` stored tickers without normalising → `[t.upper().strip() for t in tickers]`
3. `SimulatorDataSource` missing normalisation in `add_ticker`/`remove_ticker` → already present; finding was incorrect

---

## Demo

A Rich terminal dashboard is available:

```bash
cd backend
uv run market_data_demo.py
```

Displays a live-updating table with all 10 tickers showing:
- Current price with green/red colouring
- Tick-to-tick change and change %
- Daily change % (from open/seed price)
- Unicode sparkline chart (last 40 price points from `cache.get_history()`)
- Event log for notable moves (>1% per tick)
- Session summary on exit

Runs for 60 seconds or until Ctrl+C.

---

## Usage for Downstream Code

```python
from app.market import PriceCache, create_market_data_source, create_stream_router

# Startup (in FastAPI lifespan)
cache = PriceCache()
source = create_market_data_source(cache)   # reads MASSIVE_API_KEY env var
await source.start(["AAPL", "GOOGL", "MSFT", ...])

# Include SSE route
app.include_router(create_stream_router(cache))

# Read prices (from any route handler)
update = cache.get("AAPL")           # PriceUpdate | None
price  = cache.get_price("AAPL")     # float | None
all_prices = cache.get_all()         # dict[str, PriceUpdate]

# Price history (for chart endpoint)
history = cache.get_history("AAPL")  # list[{"price": float, "timestamp": float}]

# Dynamic watchlist — call from POST/DELETE /api/watchlist handlers
await source.add_ticker("PYPL")
await source.remove_ticker("NFLX")

# Shutdown (in FastAPI lifespan)
await source.stop()
```

### Wiring requirement

The watchlist REST handlers (`POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`) **must** call `add_ticker`/`remove_ticker` in the same request that writes to the database. There is no background reconciliation — the market data source holds its own in-memory ticker list.
