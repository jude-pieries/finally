# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `open_price`, `timestamp`, plus properties `change`, `change_percent`, `daily_change_percent`, `direction` ("up"/"down"/"flat"), `to_sse_dict()` (5-field SSE payload), and `to_dict()` (full serialization).

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None) -> PriceUpdate`
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `get_history(ticker) -> list[dict]` — rolling 200-point price history
  - `get_ticker_versions() -> dict[str, int]` — per-ticker change counters for SSE diffing
  - `remove(ticker)`
  - `version` property — global monotonic counter

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`.

  > **Wiring requirement:** The watchlist REST handlers (`POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`) **must** call `await market_data_source.add_ticker(ticker)` and `await market_data_source.remove_ticker(ticker)` in the same request that writes to the database. There is no background reconciliation — the market data source holds its own in-memory ticker list and will not pick up database changes automatically.

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set, otherwise `SimulatorDataSource`.

### SSE Streaming

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns FastAPI APIRouter
# Endpoint: GET /api/stream/prices (text/event-stream)
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`.

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
```

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated prices
```
