# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation.

## Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Structure

```
backend/
├── app/
│   └── market/           # Market data subsystem (complete)
│       ├── models.py     # PriceUpdate immutable dataclass
│       ├── cache.py      # Thread-safe PriceCache with history & versioning
│       ├── interface.py  # MarketDataSource abstract base class
│       ├── simulator.py  # GBMSimulator + SimulatorDataSource
│       ├── massive_client.py  # MassiveDataSource (Polygon.io REST)
│       ├── factory.py    # create_market_data_source() factory
│       ├── stream.py     # create_stream_router() SSE endpoint factory
│       └── seed_prices.py     # Default prices, GBM params, correlations
├── tests/
│   └── market/           # 100 tests, 97% coverage
├── market_data_demo.py   # Rich terminal dashboard demo
└── pyproject.toml
```

## Running Tests

```bash
uv run --extra dev pytest -v                    # All tests, verbose
uv run --extra dev pytest --cov=app/market      # With coverage report
uv run --extra dev ruff check app/ tests/       # Lint
```

## Demo

```bash
uv run market_data_demo.py
```

Live terminal dashboard: 10 tickers, sparklines, daily change %, event log for notable moves. Runs 60 seconds or Ctrl+C.

## Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | (unset) | If set and non-empty, uses real Polygon.io market data; otherwise uses the built-in GBM simulator |

## Market Data Public API

```python
from app.market import (
    PriceCache,
    PriceUpdate,
    MarketDataSource,
    create_market_data_source,
    create_stream_router,
)
```

**`PriceUpdate`** — immutable price snapshot:
- Fields: `ticker`, `price`, `previous_price`, `open_price`, `timestamp`
- Properties: `change`, `change_percent`, `daily_change_percent`, `direction`
- Methods: `to_sse_dict()` (5-field SSE payload), `to_dict()` (full serialisation)

**`PriceCache`** — thread-safe store:
- `update(ticker, price, timestamp=None) → PriceUpdate`
- `get(ticker) → PriceUpdate | None`
- `get_price(ticker) → float | None`
- `get_all() → dict[str, PriceUpdate]`
- `get_history(ticker) → list[{"price", "timestamp"}]` — up to 200 points
- `get_ticker_versions() → dict[str, int]` — per-ticker change counters
- `remove(ticker)`
- `version` property — global monotonic counter

**`MarketDataSource`** lifecycle:
```python
source = create_market_data_source(cache)
await source.start(tickers)      # seeds cache immediately
await source.add_ticker(ticker)  # dynamic watchlist add
await source.remove_ticker(ticker)
await source.stop()
```

**SSE endpoint** (`GET /api/stream/prices`):
- Push-on-change only — emits a JSON event when at least one ticker's price changed
- Event contains only changed tickers: `{"AAPL": {ticker, price, previous_price, open_price, timestamp}}`
- 10-second keepalive comment line to prevent proxy timeouts
- `retry: 1000` directive for automatic client reconnection

## Wiring Requirement

Watchlist REST handlers must call `add_ticker`/`remove_ticker` in the same request that modifies the database — there is no background reconciliation:

```python
# POST /api/watchlist
await market_source.add_ticker(ticker)

# DELETE /api/watchlist/{ticker}
await market_source.remove_ticker(ticker)
```
