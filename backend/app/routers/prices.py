"""Price history REST API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["prices"])


@router.get("/prices/{ticker}/history")
def get_price_history(request: Request, ticker: str) -> dict:
    """Return the rolling price history buffer for a ticker (up to 200 points)."""
    cache = request.app.state.price_cache
    normalized = ticker.strip().upper()
    history = cache.get_history(normalized)
    return {"ticker": normalized, "history": history}
