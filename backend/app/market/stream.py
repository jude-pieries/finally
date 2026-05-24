"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 10.0  # seconds; emit ": keepalive" if no data sent in this window
_POLL_INTERVAL = 0.5        # seconds; how often to check for cache changes


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Return a FastAPI APIRouter with the SSE /prices endpoint.

    Creates a fresh router on each call — safe to call from tests or after hot reload.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint for live price updates.

        Emits a JSON event only when at least one ticker's price has changed.
        Between data events, emits a comment-only keepalive every 10 seconds
        to prevent proxy timeouts.

        Event format:
            data: {"AAPL": {"ticker": "AAPL", "price": 191.25,
                            "previous_price": 190.50, "open_price": 190.00,
                            "timestamp": 1717435200.0}, ...}

        Only tickers that actually changed are included in each event.
        """
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted events.

    Uses per-ticker version counters to emit only tickers that changed since
    the last emission. Falls back to a comment keepalive every 10 seconds
    when nothing has changed.
    """
    yield "retry: 1000\n\n"

    last_seen_versions: dict[str, int] = {}
    last_emit_at: float = time.monotonic()

    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            now = time.monotonic()
            current_versions = price_cache.get_ticker_versions()

            changed: dict[str, dict] = {}
            for ticker, version in current_versions.items():
                if version != last_seen_versions.get(ticker, -1):
                    update = price_cache.get(ticker)
                    if update is not None:
                        changed[ticker] = update.to_sse_dict()
                    last_seen_versions[ticker] = version

            # Prune versions for tickers removed from the cache
            for ticker in set(last_seen_versions) - set(current_versions):
                del last_seen_versions[ticker]

            if changed:
                yield f"data: {json.dumps(changed)}\n\n"
                last_emit_at = now
            elif now - last_emit_at >= _KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_emit_at = now

            await asyncio.sleep(_POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
