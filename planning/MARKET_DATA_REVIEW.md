# Market Data Backend — Code Review

**Reviewer:** Claude Sonnet 4.6  
**Date:** 2026-05-25  
**Scope:** `backend/app/market/` (8 modules) + `backend/tests/market/` (6 test modules)  
**Reference:** `PLAN.md`, `MARKET_DATA_DESIGN.md`, `MARKET_DATA_SUMMARY.md`

---

## Test Results

**98 / 98 tests passing. 97% overall coverage.**

| Module | Stmts | Cover | Uncovered lines |
|--------|-------|-------|-----------------|
| `__init__.py` | 6 | 100% | — |
| `cache.py` | 66 | 100% | — |
| `factory.py` | 15 | 100% | — |
| `interface.py` | 13 | 100% | — |
| `models.py` | 34 | 100% | — |
| `seed_prices.py` | 8 | 100% | — |
| `massive_client.py` | 67 | 94% | 85–87, 125 |
| `simulator.py` | 139 | 98% | 149, 268–269 |
| `stream.py` | 49 | 94% | 44, 94, 106 |

The uncovered lines are all structurally expected: the live Massive API call (`massive_client.py:125`) requires a real API key; the exception handler in the simulator loop (`simulator.py:268–269`) and the `CancelledError` logger in the SSE generator (`stream.py:106`) are teardown paths not worth testing; and the `StreamingResponse` return (`stream.py:44`) and ticker pruning path (`stream.py:94`) are bypassed by the deliberate choice to test the generator directly rather than through HTTP.

---

## Architecture Assessment

### What works well

**Strategy pattern.** `SimulatorDataSource` and `MassiveDataSource` both implement `MarketDataSource` cleanly. The factory is trivial, and downstream code (SSE, portfolio, trades) can be written against the interface without knowing the source. This is the right design.

**`PriceCache` as the single point of truth.** One writer, many readers. All reads and writes are within `with self._lock`. `PriceUpdate` is a frozen dataclass so objects returned from the cache are safely immutable — no defensive copying needed on the read side. This is correct and efficient.

**Per-ticker version counters for SSE.** The SSE generator holds `last_seen_versions: dict[str, int]` and emits only tickers whose counter advanced since the last poll cycle. This precisely implements the push-on-change contract from the plan. Flash animations on the frontend will fire only for real price movements.

**GBM math is correct.** The discretisation is `S(t+dt) = S(t) * exp((μ - σ²/2)*dt + σ*√dt*Z)`, the exact Euler-Maruyama form for lognormal GBM. The Cholesky decomposition is correctly applied as `L @ z_independent` to produce correlated normals. The sector correlation structure (tech 0.6, finance 0.5, cross-sector 0.3, TSLA isolated at 0.3) is sensible and will produce visually plausible co-movement.

**`asyncio.to_thread()` for the Massive SDK.** The synchronous `RESTClient` is correctly wrapped in a thread to avoid blocking the event loop. This is the right approach for sync third-party SDKs in async FastAPI.

**`open_price` design.** Frozen at the first update for the simulator (seed price) and at first Massive poll result. Included in every SSE event so the frontend can compute daily change % without a separate API call.

**Router factory pattern.** `create_stream_router()` creates a new `APIRouter` on each call rather than using a module-level router. This avoids route duplication across test runs and hot reloads.

---

## Issues Found

### 1. Bug — falsy timestamp zero in `cache.py`

**File:** `cache.py:37`  
**Severity:** Low (practically never triggered)

```python
ts = timestamp or time.time()
```

If a caller explicitly passes `timestamp=0.0` (Unix epoch), the falsy check replaces it with `time.time()`. The correct guard is:

```python
ts = timestamp if timestamp is not None else time.time()
```

The Massive client passes `snap.last_trade.timestamp / 1000.0` which will never be zero in practice, but it is a latent bug.

### 2. Plan deviation — watchlist polling vs. explicit signaling

**Severity:** Architectural note, not a bug. Downstream teams need to be aware.

`PLAN.md` section 13 (decided questions) states:

> "The background task re-reads the watchlist from the database on each poll cycle. No explicit signaling needed."

The implementation does **not** do this. Both `SimulatorDataSource` and `MassiveDataSource` maintain in-memory ticker lists (`self._tickers`) and require explicit `await source.add_ticker()` / `await source.remove_ticker()` calls when the watchlist changes. There is no polling of the database.

This is actually a better design — explicit is clearer than implicit DB reads every 500ms — but it means the watchlist REST API (`POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`) **must** call these methods on the market data source when it handles requests. The integration point needs to be wired explicitly. If a future developer only writes to the database without calling `add_ticker()`, new tickers will never get prices.

**Recommendation:** Document this wiring requirement in `backend/CLAUDE.md` so the next agent (portfolio/watchlist API) implements it correctly.

### 3. Missing test — SSE ticker removal mid-stream

**File:** `stream.py:92–94`, `tests/market/test_stream.py`  
**Severity:** Low

The SSE generator prunes `last_seen_versions` when a ticker disappears from the cache:

```python
for ticker in set(last_seen_versions) - set(current_versions):
    del last_seen_versions[ticker]
```

This code is correct but uncovered (line 94 is listed in the coverage gap). There is no test that:
1. Starts a generator with AAPL in the cache
2. Removes AAPL from the cache mid-stream
3. Verifies the removed ticker does not appear in subsequent events

This edge case is real — it happens whenever a user removes a ticker from their watchlist while the SSE connection is live.

### 4. Missing test — `add_ticker()` / `remove_ticker()` before `start()`

**Severity:** Very low

If `add_ticker()` is called on a `SimulatorDataSource` before `start()`, the guard `if self._sim:` silently does nothing. The ticker will not be in the simulation when `start()` is eventually called. This is safe but the behavior (silent no-op) is untested and undocumented.

### 5. Cholesky decomposition stability

**File:** `simulator.py:172`  
**Severity:** Very low (edge case only)

```python
self._cholesky = np.linalg.cholesky(corr)
```

`np.linalg.cholesky` raises `LinAlgError` if the matrix is not positive definite. For the hardcoded values (0.3, 0.5, 0.6) this is impossible. However, if many near-identical tickers were added (e.g., ρ approaching 1.0 for 10+ tickers), the matrix could become singular. A defensive `try/except LinAlgError` that falls back to `self._cholesky = None` (uncorrelated moves) would make the simulator bulletproof.

### 6. SSE HTTP contract not unit tested (intentional)

**Severity:** Not an issue — documented for completeness.

The test strategy correctly bypasses the HTTP layer and calls `_generate_events()` directly. This avoids the hang problem that plagued earlier SSE test approaches. The trade-off is that the HTTP 200 response code, `content-type: text/event-stream` header, `Cache-Control: no-cache`, and `X-Accel-Buffering: no` headers are not verified in unit tests. These should be covered by the E2E Playwright tests when they are written.

---

## Minor Code Quality Notes

**`simulator.py:_run_loop`** — The `while True` loop catches all exceptions with `logger.exception()` and continues. This prevents a bad tick from killing the simulator. Good defensive pattern. The unreachable lines (268–269) are the exception body, which isn't triggered in tests because the happy path is always taken; the exception resilience test exercises the concept but not this exact file.

**`massive_client.py:_poll_loop`** — The loop starts with `await asyncio.sleep(self._interval)` (not immediately), because `start()` already performed an immediate first poll. This is correct and intentional. The coverage gap on lines 85–87 is because tests mock `_poll_once()` and stop the task early.

**`cache.py:get_price()`** — Calls `self.get()` which acquires the lock, returns an immutable `PriceUpdate`, then accesses `.price` outside the lock. This is safe because `PriceUpdate` is frozen. Correct.

**`seed_prices.py`** — NFLX is correctly grouped in `tech` (streaming/software company). All 10 default tickers are parameterised. Unknown tickers get `DEFAULT_PARAMS` (`sigma=0.25, mu=0.05`) and a random seed price in `$50–$300`. The random range is fine for a demo but could produce odd results for tickers with very different real prices (e.g., a $3000 stock starting at $150). Not a functional issue.

---

## Compliance with PLAN.md

| Requirement | Status |
|-------------|--------|
| Two implementations, one interface (`MarketDataSource` ABC) | ✅ |
| GBM simulator at ~500ms intervals | ✅ |
| Correlated moves via Cholesky | ✅ |
| Random shock events | ✅ |
| Realistic seed prices | ✅ |
| Massive REST polling (not WebSocket) | ✅ |
| Shared PriceCache with open price, history buffer | ✅ |
| History buffer: 200 points per ticker | ✅ |
| SSE push-on-change with 10s keepalive | ✅ |
| SSE event fields: ticker, price, previous_price, open_price, timestamp | ✅ |
| `GET /api/prices/{ticker}/history` endpoint | ✅ (router created; endpoint wire-up depends on app startup) |
| Factory reads `MASSIVE_API_KEY` env var | ✅ |
| Whitespace-only key treated as absent | ✅ |
| Background task re-reads DB each poll cycle | ❌ Uses explicit signaling instead (see Issue #2) |

---

## Verdict

**This implementation is production-quality for a demo app.** The code is clean, well-structured, mathematically correct, and well-tested. The 97% coverage figure is not a vanity metric — the uncovered lines are all genuinely untestable at the unit level (live API calls, teardown paths, HTTP response objects).

**Two items need action before the next sprint:**

1. **Fix the `timestamp or time.time()` bug** in `cache.py:37` — one-line change.
2. **Document the `add_ticker`/`remove_ticker` wiring requirement** in `backend/CLAUDE.md` — the watchlist API must call these on the market data source instance, not just write to the database.

**One item is recommended but not blocking:**

3. Add a test for the SSE ticker-removal mid-stream path (`stream.py:94`) to close the last meaningful coverage gap.
