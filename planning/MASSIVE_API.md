# Massive API — Reference Guide

Massive (formerly Polygon.io) is the financial data provider used by FinAlly when a `MASSIVE_API_KEY` is set. The Python `massive` package is a thin wrapper around the Polygon.io REST API; the two are API-compatible and share the same endpoint paths and response shapes.

---

## Installation

```bash
pip install massive        # or: uv add massive
```

Requires Python 3.9+.

---

## Authentication

All requests require an API key, passed to `RESTClient` at construction time.

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_API_KEY_HERE")
```

The key is sourced from the Massive dashboard: `https://massive.com/dashboard/api-keys`.

Invalid or missing keys return HTTP 401. The client raises an exception on non-2xx responses.

---

## Batch Snapshot — The Core Endpoint

For FinAlly's use case (10–20 tickers polled on a regular interval), the batch snapshot is the right tool. It returns the latest trade, quote, and OHLCV data for all requested tickers in a single API call.

### REST

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
    ?tickers=AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA,META,JPM,V,NFLX
```

### Python SDK

```python
from massive.rest.models import SnapshotMarketType

snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"],
)

for snap in snapshots:
    price     = snap.last_trade.price
    timestamp = snap.last_trade.timestamp / 1000.0   # ms → seconds
    ticker    = snap.ticker
    print(f"{ticker}: ${price:.2f}  (ts={timestamp})")
```

`get_snapshot_all()` is synchronous. In an async context (FastAPI), wrap it in `asyncio.to_thread`:

```python
import asyncio

snapshots = await asyncio.to_thread(
    client.get_snapshot_all,
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "TSLA"],
)
```

### Sample Response JSON

```json
{
  "status": "OK",
  "count": 2,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600,
      "day": {
        "o": 151.25,
        "h": 152.00,
        "l": 150.00,
        "c": 150.50,
        "v": 52000000,
        "vw": 150.45
      },
      "prevDay": {
        "c": 150.624,
        "v": 45000000,
        "vw": 150.60
      },
      "lastTrade": {
        "p": 150.50,
        "s": 100,
        "t": 1605192894630,
        "x": 1,
        "i": "12345"
      },
      "lastQuote": {
        "P": 150.52,
        "S": 1,
        "p": 150.51,
        "s": 2,
        "t": 1605192894630
      }
    },
    {
      "ticker": "TSLA",
      "todaysChange": 2.45,
      "todaysChangePerc": 1.20,
      "updated": 1605192894630916600,
      "day": {
        "o": 203.00,
        "h": 207.00,
        "l": 204.50,
        "c": 205.35,
        "v": 38000000,
        "vw": 205.20
      },
      "prevDay": {
        "c": 202.90,
        "v": 42000000,
        "vw": 203.00
      },
      "lastTrade": {
        "p": 205.35,
        "s": 50,
        "t": 1605192894620,
        "x": 4
      }
    }
  ]
}
```

Key fields used by FinAlly:

| Field | Path | Notes |
|-------|------|-------|
| Last trade price | `snap.last_trade.price` | Current market price |
| Last trade timestamp | `snap.last_trade.timestamp` | Unix **milliseconds** — divide by 1000 for seconds |
| Ticker symbol | `snap.ticker` | Uppercase, e.g. `"AAPL"` |
| Day open | `snap.day.open` | Used to compute daily change % |
| Day close (current) | `snap.day.close` | Alternative price source |

---

## Single Ticker Snapshot

For a single ticker or ad-hoc lookups:

```python
snap = client.get_snapshot_ticker(
    market_type=SnapshotMarketType.STOCKS,
    ticker="AAPL",
)
print(snap.last_trade.price)
```

REST equivalent: `GET /v2/snapshot/locale/us/markets/stocks/tickers/AAPL`

---

## End-of-Day Prices

Historical daily OHLCV for a ticker on a specific date:

```python
eod = client.get_open_close_agg(
    ticker="AAPL",
    date="2024-01-15",
    adjusted=True,
)
print(eod.open, eod.close, eod.high, eod.low, eod.volume)
```

REST equivalent: `GET /v1/open-close/AAPL/2024-01-15?adjusted=true`

Sample response:

```json
{
  "status": "OK",
  "from": "2024-01-15",
  "symbol": "AAPL",
  "open": 183.92,
  "high": 185.15,
  "low": 182.73,
  "close": 183.31,
  "volume": 47876800,
  "afterHours": 183.25,
  "preMarket": 184.00
}
```

---

## Rate Limits

| Plan | REST requests/min | Recommended poll interval |
|------|------------------|--------------------------|
| Free | 5 | 15 s |
| Starter | Unlimited | 5–10 s |
| Advanced | Unlimited | 2–5 s |
| Business | Unlimited | 1–2 s |

Rate limit response: HTTP 429. The `Retry-After` header tells you how many seconds to wait. The `massive` client does not auto-retry — implement a backoff loop if needed.

FinAlly uses a conservative 15-second default interval, safe for the free tier. Adjust via `MassiveDataSource(poll_interval=5.0)` for paid plans.

---

## Error Handling

```python
try:
    snapshots = await asyncio.to_thread(
        client.get_snapshot_all,
        market_type=SnapshotMarketType.STOCKS,
        tickers=tickers,
    )
except Exception as e:
    # Common cases:
    # - 401: bad API key
    # - 429: rate limit exceeded
    # - network error / timeout
    logger.error("Massive poll failed: %s", e)
    # Don't re-raise in a poll loop — retry on the next interval
```

Per-ticker errors (e.g. snapshot missing `last_trade`):

```python
for snap in snapshots:
    try:
        price = snap.last_trade.price
        ts    = snap.last_trade.timestamp / 1000.0
    except (AttributeError, TypeError) as e:
        logger.warning("Skipping %s: %s", getattr(snap, "ticker", "?"), e)
        continue
```

---

## WebSocket Streaming (Not Used in FinAlly)

The `massive` package includes a `WebSocketClient` for real-time trade and quote events. FinAlly uses REST polling instead (simpler, works on all plan tiers), but the WebSocket API is available if needed:

```python
from massive import WebSocketClient

ws = WebSocketClient(
    api_key="YOUR_KEY",
    subscriptions=["T.AAPL", "T.TSLA", "Q.MSFT"],  # T=trades, Q=quotes
)

def on_message(msgs):
    for m in msgs:
        print(m)  # {"ev": "T", "sym": "AAPL", "p": 150.50, "s": 100, ...}

ws.run(handle_msg=on_message)
```

Subscription formats:
- `T.<TICKER>` — trade events (has price, size, timestamp)
- `Q.<TICKER>` — quote events (has bid/ask)
- `T.*` — all trades across all tickers

WebSocket requires Stocks Advanced or higher plan for real-time data.

---

## Complete Working Example

```python
import asyncio
import logging
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


async def poll_prices(api_key: str, interval: float = 15.0) -> None:
    client = RESTClient(api_key=api_key)

    while True:
        try:
            snapshots = await asyncio.to_thread(
                client.get_snapshot_all,
                market_type=SnapshotMarketType.STOCKS,
                tickers=TICKERS,
            )
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    ts    = snap.last_trade.timestamp / 1000.0
                    logger.info("%s  $%.2f  (t=%s)", snap.ticker, price, ts)
                except (AttributeError, TypeError) as e:
                    logger.warning("Skipping %s: %s", getattr(snap, "ticker", "?"), e)

        except Exception as e:
            logger.error("Poll failed: %s", e)

        await asyncio.sleep(interval)


if __name__ == "__main__":
    import os
    asyncio.run(poll_prices(api_key=os.environ["MASSIVE_API_KEY"]))
```
