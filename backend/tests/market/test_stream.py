"""Tests for the SSE streaming endpoint."""

from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


def make_request(disconnected: bool = False) -> MagicMock:
    """Mock FastAPI Request that reports a fixed disconnection state."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = "test-client"
    req.is_disconnected = AsyncMock(return_value=disconnected)
    return req


async def collect_events(
    cache: PriceCache,
    request: MagicMock,
    *,
    max_events: int = 3,
    timeout: float = 2.0,
) -> list[str]:
    """Collect up to `max_events` SSE lines from _generate_events."""
    events = []
    gen = _generate_events(cache, request)
    try:
        async with asyncio.timeout(timeout):
            async for line in gen:
                events.append(line)
                if len(events) >= max_events:
                    break
    except TimeoutError:
        pass
    finally:
        await gen.aclose()
    return events


@pytest.mark.asyncio
class TestCreateStreamRouter:
    async def test_returns_fresh_router_each_call(self):
        cache = PriceCache()
        router1 = create_stream_router(cache)
        router2 = create_stream_router(cache)
        assert router1 is not router2


@pytest.mark.asyncio
class TestGenerateEvents:
    async def test_first_yield_is_retry_directive(self):
        cache = PriceCache()
        events = await collect_events(cache, make_request(), max_events=1)
        assert len(events) == 1
        assert "retry: 1000" in events[0]

    async def test_emits_data_event_when_prices_present(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        events = await collect_events(cache, make_request(), max_events=2)
        data_events = [e for e in events if e.startswith("data:")]
        assert len(data_events) >= 1
        payload = json.loads(data_events[0][5:].strip())
        assert "AAPL" in payload

    async def test_sse_event_has_exactly_five_fields(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        events = await collect_events(cache, make_request(), max_events=2)
        data_events = [e for e in events if e.startswith("data:")]
        payload = json.loads(data_events[0][5:].strip())
        assert set(payload["AAPL"].keys()) == {
            "ticker", "price", "previous_price", "open_price", "timestamp"
        }

    async def test_open_price_in_event(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)   # open price frozen here
        cache.update("AAPL", 195.0)   # price moves
        events = await collect_events(cache, make_request(), max_events=2)
        data_events = [e for e in events if e.startswith("data:")]
        payload = json.loads(data_events[0][5:].strip())
        assert payload["AAPL"]["open_price"] == 190.0
        assert payload["AAPL"]["price"] == 195.0

    async def test_only_changed_tickers_emitted(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("TSLA", 250.0)

        events = await collect_events(cache, make_request(), max_events=2)
        data_events = [e for e in events if e.startswith("data:")]
        # First event: both tickers (both unseen)
        first = json.loads(data_events[0][5:].strip())
        assert "AAPL" in first
        assert "TSLA" in first

        # Now update only TSLA and start a new generator
        cache.update("TSLA", 255.0)

        # Seed last_seen so AAPL and TSLA are already "seen" at their current versions,
        # then update TSLA again — the next event should contain only TSLA.
        # We simulate this by collecting events after a targeted update.
        req = make_request()
        gen = _generate_events(cache, req)
        # Consume retry + first data event (absorbs current state)
        collected = []
        async with asyncio.timeout(2.0):
            async for line in gen:
                collected.append(line)
                if len([e for e in collected if e.startswith("data:")]) >= 1:
                    break

        # Now update only TSLA
        cache.update("TSLA", 260.0)

        # The next data event must contain only TSLA
        async with asyncio.timeout(2.0):
            async for line in gen:
                if line.startswith("data:"):
                    second = json.loads(line[5:].strip())
                    assert "TSLA" in second
                    assert "AAPL" not in second
                    break

        await gen.aclose()

    async def test_stops_on_disconnect(self):
        cache = PriceCache()
        # Disconnected immediately
        req = make_request(disconnected=True)
        events = await collect_events(cache, req, max_events=10, timeout=2.0)
        # Should only have the retry directive — loop exits on first disconnect check
        assert len(events) == 1
        assert "retry" in events[0]

    async def test_keepalive_emitted_when_no_changes(self):
        from app.market import stream as stream_module
        original = stream_module._KEEPALIVE_INTERVAL

        try:
            # Shorten keepalive interval for the test
            stream_module._KEEPALIVE_INTERVAL = 0.1

            cache = PriceCache()  # No prices — nothing will change
            req = make_request()
            events = await collect_events(cache, req, max_events=3, timeout=2.0)
            keepalives = [e for e in events if e.startswith(": keepalive")]
            assert len(keepalives) >= 1
        finally:
            stream_module._KEEPALIVE_INTERVAL = original
