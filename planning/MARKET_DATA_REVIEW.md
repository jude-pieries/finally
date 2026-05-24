# Market Data Backend — Code Review

**Date:** 2026-05-25  
**Branch:** `feature/market-data-review`  
**Reviewer:** Claude Sonnet 4.6  
**Scope:** `backend/app/market/` (8 modules, ~400 LOC) + `backend/tests/market/` (7 test modules, ~550 LOC)  

---

## Test Results

```
100 passed in 3.14s
```

**Coverage (97% overall):**

| Module | Stmts | Miss | Cover | Uncovered lines |
|---|---|---|---|---|
| `__init__.py` | 6 | 0 | **100%** | — |
| `cache.py` | 66 | 0 | **100%** | — |
| `factory.py` | 15 | 0 | **100%** | — |
| `interface.py` | 13 | 0 | **100%** | — |
| `models.py` | 34 | 0 | **100%** | — |
| `seed_prices.py` | 8 | 0 | **100%** | — |
| `massive_client.py` | 67 | 4 | 94% | 85-87, 125 |
| `simulator.py` | 145 | 6 | 96% | 149, 174-176, 274-275 |
| `stream.py` | 49 | 2 | 96% | 44, 106 |

---

## Lint

```
tests/market/test_stream.py:3 I001 Import block is un-sorted or un-formatted
```

One fixable issue: `from unittest.mock import AsyncMock, MagicMock` is interleaved with third-party imports instead of being grouped with stdlib. Auto-fixable with `ruff --fix`.

---

## Module-by-Module Review

### `models.py` — PriceUpdate ✅

Clean, well-structured frozen dataclass. The dual-serializer pattern (`to_sse_dict()` / `to_dict()`) is the right call:
- `to_sse_dict()` exposes exactly the five SSE-contract fields, nothing more.
- `to_dict()` exposes all computed properties for portfolio/trade API consumers.

Division-by-zero guards are present in `change_percent` and `daily_change_percent`. Immutability enforced via `frozen=True, slots=True`.

**No issues.**

---

### `cache.py` — PriceCache ✅

Well-structured. Every public method acquires the lock, including the `version` property (which was a known bug in an earlier version). The falsy-zero bug for `timestamp` is correctly fixed with `timestamp if timestamp is not None else time.time()`.

The three additions beyond the original design are all implemented correctly:
- **`open_price`** — frozen at first `update()` call via `_open_prices` dict, never overwritten.
- **200-point history** — `deque(maxlen=200)` per ticker; auto-evicts oldest entries.
- **Per-ticker version counters** — independent of the global version; increment on every `update()`, removed on `remove()`.

`remove()` clears all four per-ticker data structures and increments the global version to signal SSE that the ticker list changed. Correct.

**No issues.**

---

### `interface.py` — MarketDataSource ✅

Minimal and correct. Five abstract methods cover the full lifecycle. Docstrings are clear about which calls are idempotent and which may only be called once.

**No issues.**

---

### `stream.py` — SSE Generator ✅

The three previous problems are all resolved:
1. Router is created inside `create_stream_router()`, not at module level.
2. Push-on-change uses per-ticker version diffing — stale tickers are never re-emitted.
3. Keepalive fires after `_KEEPALIVE_INTERVAL` (10s) with no data emission.

Removed-ticker pruning is correct: tickers that disappear from `get_ticker_versions()` are removed from `last_seen_versions` so they don't ghost in future diffs.

`X-Accel-Buffering: no` header is present to prevent nginx from buffering the SSE stream in proxied deployments.

**Uncovered lines (not bugs):**
- Line 44: The `stream_prices` route handler body — tests call `_generate_events` directly, bypassing the HTTP layer. The route itself is covered by the router factory test.
- Line 106: The `asyncio.CancelledError` branch — only triggered when the task is externally cancelled; not exercised by the current test helpers.

**No correctness issues.**

---

### `simulator.py` — GBM Simulator ✅

GBM formula is mathematically correct:  
`S(t+dt) = S(t) × exp((μ − ½σ²)dt + σ√dt × Z)`

Cholesky decomposition for correlated moves is correctly applied via matrix multiplication `L @ z`. The `LinAlgError` fallback to uncorrelated moves is present (though untested — the default correlation matrix is always positive semi-definite for the given sector groupings).

**Minor finding — inconsistent normalization in `SimulatorDataSource`:**  
`MassiveDataSource.add_ticker()` and `remove_ticker()` both call `.upper().strip()` to normalise ticker strings. `SimulatorDataSource` does not. If a caller passes `"aapl"` or `" AAPL "`, the simulator and cache would receive un-normalised keys, diverging from the Massive behaviour. Low risk given the REST handlers will normalise before calling, but worth making consistent.

**Uncovered lines (not bugs):**
- Line 149: `if ticker in self._prices: return` inside `_add_ticker_internal` — the duplicate-add guard. Covered indirectly by `test_add_duplicate_is_noop` at the `GBMSimulator.add_ticker()` level.
- Lines 174-176: `LinAlgError` handler in `_rebuild_cholesky` — requires a degenerate correlation matrix to trigger.
- Lines 274-275: `logger.exception(...)` in `_run_loop` — requires a simulator step to raise an unexpected exception.

---

### `massive_client.py` — Massive REST Poller ✅

`asyncio.to_thread()` correctly wraps the synchronous `RESTClient` call to avoid blocking the event loop. The `start()` method does an immediate first poll so the cache has data before the first SSE connection.

The exception hierarchy in `_poll_once` is correct: per-snapshot `AttributeError`/`TypeError` are caught individually (skip bad snapshots, continue processing good ones); the outer `except Exception` catches transport errors (429, 401, network) and logs without re-raising so the loop retries.

**Minor finding — ticker normalisation is only in add/remove, not in `start()`:**  
`start(tickers)` stores `list(tickers)` directly without normalising. If the watchlist seeding passes un-normalised tickers, they'll be polled as-is. Again low risk in practice but inconsistent with the per-method normalisation.

**Uncovered lines (expected):**
- Lines 85-87: Part of the `_poll_loop` body — the loop's `asyncio.sleep` branch is tested via `test_stop_cancels_task` but the sleep itself is never allowed to expire in tests.
- Line 125: `_fetch_snapshots` body — the actual `RESTClient` call; correctly mocked in all tests to avoid real API calls.

---

### `factory.py` ✅

Simple and correct. Whitespace-only key correctly falls through to the simulator path via `.strip()`. Seven tests cover all input variants.

**No issues.**

---

### `seed_prices.py` ✅

All ten default tickers have realistic prices and per-ticker volatility/drift parameters. Correlation groupings are consistent with the simulator's `_pairwise_correlation` logic.

**No issues.**

---

## Summary of Findings

| # | Severity | Location | Finding |
|---|---|---|---|
| 1 | Low | `tests/market/test_stream.py:3` | Unsorted import block — auto-fixable with `ruff --fix` |
| 2 | Low | `simulator.py:246, 256` | `SimulatorDataSource.add_ticker()` / `remove_ticker()` missing `.upper().strip()` normalisation (unlike `MassiveDataSource`) |
| 3 | Low | `massive_client.py:43` | `start()` stores tickers without normalising (inconsistent with per-method normalisation) |
| 4 | Info | `stream.py:106` | `CancelledError` branch untested — low value to add given tests use generator-level helpers |
| 5 | Info | `simulator.py:174-176` | `LinAlgError` fallback untested — would require a degenerate correlation matrix |

---

## Verdict

**LGTM — ready to build on.**

The market data backend is correct, well-tested, and consistent with the design spec. All previously-identified review blockers have been resolved: `open_price` is present, SSE is push-on-change only, keepalive is implemented, per-ticker versioning is correct, the router-singleton bug is fixed, and the timestamp falsy-zero bug is fixed.

The two normalisation inconsistencies (#2, #3) are the only substantive findings. They are low risk given the REST handlers upstream will normalise, but fixing them would make the two data sources fully symmetric — a one-line change in each.

The single lint error (#1) is trivially auto-fixable and has no correctness impact.

**Action items before shipping:**

- [ ] `ruff --fix tests/market/test_stream.py` — fix unsorted imports (1 min)
- [ ] Add `.upper().strip()` to `SimulatorDataSource.add_ticker()` and `remove_ticker()` (2 min)
- [ ] Add `.upper().strip()` normalisation to `MassiveDataSource.start()` tickers list (2 min)
