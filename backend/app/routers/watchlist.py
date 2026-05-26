"""Watchlist REST API routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from app.db import add_to_watchlist, get_watchlist, remove_from_watchlist

router = APIRouter(tags=["watchlist"])

_TICKER_RE = re.compile(r"^[A-Z0-9]{1,10}$")


class AddTickerRequest(BaseModel):
    """Request body for POST /watchlist."""

    ticker: str

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not _TICKER_RE.match(normalized):
            raise ValueError(
                "ticker must be 1–10 alphanumeric characters (letters and digits only)"
            )
        return normalized


@router.get("/watchlist")
def get_watchlist_route(request: Request) -> dict:
    """Return the current watchlist as a list of ticker symbols."""
    db_path: str = request.app.state.db_path
    tickers = get_watchlist(db_path)
    return {"tickers": tickers}


@router.post("/watchlist")
async def add_ticker(request: Request, body: AddTickerRequest) -> dict:
    """Add a ticker to the watchlist. Returns 409 if ticker is already present."""
    db_path: str = request.app.state.db_path
    market_source = request.app.state.market_source

    try:
        add_to_watchlist(db_path, body.ticker)
    except ValueError:
        raise HTTPException(status_code=409, detail="Ticker already in watchlist")

    await market_source.add_ticker(body.ticker)
    return {"ticker": body.ticker}


@router.delete("/watchlist/{ticker}")
async def remove_ticker(request: Request, ticker: str) -> Response:
    """Remove a ticker from the watchlist. Returns 404 if ticker is not found."""
    db_path: str = request.app.state.db_path
    market_source = request.app.state.market_source

    normalized = ticker.strip().upper()
    try:
        remove_from_watchlist(db_path, normalized)
    except ValueError:
        raise HTTPException(status_code=404, detail="Ticker not in watchlist")

    await market_source.remove_ticker(normalized)
    return Response(status_code=204)
