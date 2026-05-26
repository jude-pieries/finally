"""System / health-check routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health")
def health_check(request: Request) -> dict:
    """Return service health and market data configuration."""
    market_source = request.app.state.market_source
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    market_data = "massive" if api_key else "simulator"
    return {
        "status": "ok",
        "market_data": market_data,
        "tickers": len(market_source.get_tickers()),
    }
