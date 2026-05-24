# Market Data Backend — Code Review

**Reviewer:** Claude Opus 4.7 (custom_reviewer)
**Date:** 2026-05-25
**Scope:** `backend/app/market/` (8 modules) + `backend/tests/market/` (6 test modules, 98 tests)
**Reference:** `PLAN.md` sections 6 and 8, `MARKET_DATA_DESIGN.md`, `MARKET_DATA_SUMMARY.md`

---

## Test Results

**98 / 98 tests passing. 97% overall coverage.**

| Module | Stmts | Cover | Uncovered lines |
|--------|------:|------:|-----------------|
| `__init__.py` | 6 | 100% | — |
| `cache.py` | 66 | 100% | — |
| `factory.py` | 15 | 100% | — |
| `interface.py` | 13 | 100% | — |
| `models.py` | 34 | 100% | — |
| `seed_prices.py` | 8 | 100% | — |
| `massive_client.py` | 67 | 94% | 85–87, 125 |
| `simulator.py` | 139 | 98% | 149, 268–269 |
| `stream.py` | 49 | 94% | 44, 94, 106 |

The uncovered lines fall into three legitimate categories: (a) the live external API call (`massive_client.py:125`), (b) exception handler bodies and `CancelledError` teardown paths (`simulator.py:268–269`, `stream.py:106`), and (c) paths exercised by the HTTP layer rather than generator-level unit tests (`stream.py:44`, `simulator.py:149`). The exception is `stream.py:94` — the ticker pruning path — which is genuinely testable at the generator level and should be covered (see Issue #3).

---

## Architecture Assessment

### What works well

**Strategy pattern is clean.** `MarketDataSource` ABC in `interface.py` has the minimal, correct surface: `start / stop / add_ticker / remove_ticker / get_tickers`. Both implementations conform without leaking provider-specific details.

**`PriceCache` is the correct single point of synchronisation.** All public reads and writes are guarded by `self._lock`. `PriceUpdate` is `@dataclass(frozen=True, slots=True)` so cache reads return immutable values — no defensive copying needed by callers. The shallow copies in `get_all()` and `get_ticker_versions()` are the right granularity: snapshots of references to immutable objects.

**Per-ticker version counters are the right SSE primitive.** `_generate_events` holds `last_seen_versions: dict[str, int]` and emits only tickers whose counter advanced. This is `O(n_tickers)` per poll and precisely implements the push-on-change semantics from PLAN.md section 6.

**GBM math is correct.** The discretisation on `simulator.py:99–101` is the standard Euler–Maruyama form for lognormal GBM:
```
S(t+dt) = S(t) * exp((μ - σ²/2)*dt + σ*√dt*Z)
```
The Cholesky decomposition is correctly applied as `L @ z_independent` to produce correlated standard normals. `TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600` and `DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR ≈ 8.48e-8` is correct — sub-cent moves per tick that accumulate to realistic daily ranges.

**`asyncio.to_thread()` for the synchronous Massive SDK.** `RESTClient.get_snapshot_all` is synchronous; wrapping it in `asyncio.to_thread` correctly prevents blocking the event loop.

**`open_price` design.** Frozen on the first `update()` call, included in every SSE event via `to_sse_dict()`. This implements the PLAN.md section 13 decision precisely.

**Router-factory pattern.** `create_stream_router()` returns a fresh `APIRouter` per call — avoids the duplicate-route registration bug that hits FastAPI hot reload and pytest reuse.

---

## Issues Found

### 1. Bug — falsy-zero timestamp in `PriceCache.update`

**File:** `cache.py:37`
**Severity:** Low (latent — never triggered in practice today)

```python
ts = timestamp or time.time()
```

If a caller passes `timestamp=0.0`, the `or` falls through to `time.time()`. The Massive client computes `snap.last_trade.timestamp / 1000.0` — a malformed response could produce `0.0`, which would silently substitute the local wall clock and create a hard-to-diagnose discrepancy.

**Fix:**
```python
ts = timestamp if timestamp is not None else time.time()
```
Add a regression test asserting `cache.update("X", 100.0, timestamp=0.0).timestamp == 0.0`.

---

### 2. Design contract drift — explicit signalling vs. DB polling

**Files:** `simulator.py:242–255`, `massive_client.py:66–76`, `interface.py:42–53`
**Severity:** Architectural — must be communicated to downstream agents before the watchlist API is built.

PLAN.md section 13 (decided questions) states:

> "The background task re-reads the watchlist from the database on each poll cycle. No explicit signaling needed."

The implementation does the opposite: both sources hold in-memory ticker lists and require explicit `await source.add_ticker()` / `remove_ticker()` calls. There is zero database awareness in `app/market/`.

This implementation choice is **better** than the plan's decision — coupling the 500ms tick to a synchronous SQLite query would be wasteful. But it must be documented because a future agent implementing the watchlist API who reads only PLAN.md will write `INSERT INTO watchlist (...)` and expect new prices to flow. They won't.

**Fix:** Add a paragraph to `backend/CLAUDE.md` explicitly stating: "The watchlist REST handlers must call `market_data_source.add_ticker(t)` and `market_data_source.remove_ticker(t)` in the same request that modifies the database. There is no background reconciliation loop."

---

### 3. Missing test — SSE ticker pruning path mid-stream

**Files:** `stream.py:92–94`, `tests/market/test_stream.py`
**Severity:** Low — but a real production path.

```python
for ticker in set(last_seen_versions) - set(current_versions):
    del last_seen_versions[ticker]
```

This runs every time a user removes a ticker from the watchlist while an SSE connection is live. Unlike the other uncovered lines (exception handlers, `StreamingResponse` construction), this is plain happy-path logic exercisable via the generator interface already used by the other tests.

**Fix:** Add a test that seeds AAPL, starts the generator, consumes the first data event, calls `cache.remove("AAPL")`, then asserts the next data event does not mention AAPL (or a keepalive is emitted).

---

### 4. Ticker normalisation inconsistency between implementations

**Files:** `massive_client.py:67`, `simulator.py:242–249`
**Severity:** Low — but a real behaviour difference.

```python
# MassiveDataSource
async def add_ticker(self, ticker: str) -> None:
    ticker = ticker.upper().strip()   # normalised

# SimulatorDataSource
async def add_ticker(self, ticker: str) -> None:
    if self._sim:
        self._sim.add_ticker(ticker)   # not normalised
```

A caller adding `"  aapl  "` gets `AAPL` in the Massive cache and `  aapl  ` (distinct key) in the simulator. Same asymmetry in `remove_ticker`.

**Fix:** normalise at the API boundary (watchlist route handler) and document the contract as "callers pass canonical uppercase tickers", or push normalisation into the abstract interface.

---

### 5. `add_ticker` / `remove_ticker` before `start()` — inconsistent behaviour

**Files:** `simulator.py:242`, `massive_client.py:66`
**Severity:** Very low.

`SimulatorDataSource.add_ticker()` silently no-ops when `self._sim is None` (before `start()`). `MassiveDataSource.add_ticker()` appends to `self._tickers` unconditionally — so it works before `start()`. The two implementations behave differently for the same pre-`start` call.

**Fix:** either raise `RuntimeError("add_ticker called before start()")` in both, or accept the call in both (buffering tickers to be added on `start()`). Don't have asymmetric silent failure.

---

### 6. SSE poll interval and simulator update interval are implicitly coupled

**Files:** `simulator.py:210` (`update_interval=0.5`), `stream.py:19` (`_POLL_INTERVAL = 0.5`)
**Severity:** Informational — no bug today.

Both constants are 0.5s and appear to be independently chosen. In the worst case, a simulator tick at time `t` is read at SSE poll `t + 0.5s`, giving ~1s visible latency — acceptable for a demo. But because the constants must be approximately aligned (or the SSE generator starves / spams), they should be commented as related.

**Fix:** A single comment in `stream.py:19` noting the relationship, or a shared `TICK_INTERVAL` constant.

---

### 7. Cholesky stability for pathological correlation matrices

**File:** `simulator.py:172`
**Severity:** Very low (edge case only).

`np.linalg.cholesky` raises `LinAlgError` on a non-positive-definite matrix. For the hardcoded values (max ρ = 0.6) this is impossible. If future ticker additions push correlations higher or a code change tightens the values, this can break.

**Fix:**
```python
try:
    self._cholesky = np.linalg.cholesky(corr)
except np.linalg.LinAlgError:
    logger.warning("Correlation matrix not positive definite; using uncorrelated moves")
    self._cholesky = None
```

---

### 8. History endpoint not yet wired to a router

**Severity:** Gap — tracked here for the next sprint.

`PriceCache.get_history(ticker)` exists and is tested. PLAN.md section 8 requires `GET /api/prices/{ticker}/history`. No FastAPI router exposes it yet. A `create_prices_router(cache)` factory (mirroring `create_stream_router`) is the obvious next step and belongs in the portfolio/API sprint.

---

## Spec Compliance (PLAN.md sections 6 and 8)

| Requirement | Status | Notes |
|-------------|--------|-------|
| Two implementations, one interface | ✅ | `MarketDataSource` ABC clean |
| GBM at ~500ms intervals | ✅ | `update_interval=0.5`, math correct |
| Correlated moves via Cholesky | ✅ | Sector groups, TSLA isolated |
| Random shock events 2–5% | ✅ | `event_probability=0.001` |
| Realistic seed prices | ✅ | 10 default tickers |
| Massive REST polling | ✅ | Free-tier 15s, configurable |
| Shared `PriceCache` with open price | ✅ | Frozen on first update |
| History buffer 200 points | ✅ | `deque(maxlen=200)` |
| SSE push-on-change | ✅ | Per-ticker version counters |
| SSE keepalive every 10s | ✅ | `_KEEPALIVE_INTERVAL = 10.0` |
| SSE event fields = exactly 5 | ✅ | `to_sse_dict()` enforces |
| `GET /api/prices/{ticker}/history` | ❌ Not wired | `get_history()` exists; router not built yet |
| Factory reads `MASSIVE_API_KEY` | ✅ | Whitespace stripped |
| Background task re-reads DB | ❌ Deviated | Uses explicit signalling — better, but undocumented (Issue #2) |

---

## Readiness for Downstream Code

The module is ready to build on top of, with three caveats:

1. **Watchlist API must call `add_ticker` / `remove_ticker` explicitly.** See Issue #2. This must be documented before the next agent starts.

2. **Trade execution uses `cache.get_price(ticker)`** — synchronous, thread-safe, immediate. The "instant fill at current price" rule is trivially satisfied. There is no guard against stale prices (e.g., Massive failed for 60s). Acceptable for a demo.

3. **Portfolio valuation uses `cache.get_all()`** — returns a shallow copy of immutable `PriceUpdate` objects. Safe to iterate without holding the lock.

---

## Verdict

**This implementation is production-quality for the demo scope.** The math is correct, concurrency is correct, the strategy pattern is clean, and 98/98 tests at 97% coverage is a non-trivial achievement.

**Action items, prioritised:**

| # | Item | Priority |
|---|------|----------|
| 1 | Document `add_ticker` / `remove_ticker` wiring contract in `backend/CLAUDE.md` | **Blocking for next sprint** |
| 2 | Fix `timestamp or time.time()` in `cache.py:37` | High — one-line fix |
| 3 | Normalise ticker casing consistently across both implementations | High |
| 4 | Add SSE pruning test (`stream.py:94`) and falsy-zero timestamp regression test | Medium |
| 5 | Build `create_prices_router(cache)` for `GET /api/prices/{ticker}/history` | Next sprint scope |
| 6 | Make `add_ticker` before `start()` consistent across implementations | Low |
| 7 | Add Cholesky `LinAlgError` fallback | Low |
| 8 | Comment the SSE/simulator interval coupling | Low |
