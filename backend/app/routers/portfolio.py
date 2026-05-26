"""Portfolio REST API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.db import (
    execute_trade,
    get_portfolio_history,
    get_positions,
    get_user_profile,
    save_portfolio_snapshot,
)

router = APIRouter(tags=["portfolio"])


class TradeRequest(BaseModel):
    """Request body for POST /portfolio/trade."""

    ticker: str
    quantity: float
    side: Literal["buy", "sell"]

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


@router.get("/portfolio")
def get_portfolio(request: Request) -> dict:
    """Return current portfolio: cash balance, total value, and enriched positions."""
    db_path: str = request.app.state.db_path
    cache = request.app.state.price_cache

    profile = get_user_profile(db_path)
    raw_positions = get_positions(db_path)

    cash = profile["cash_balance"]
    positions = []

    for pos in raw_positions:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]

        price_update = cache.get(ticker)
        current_price = price_update.price if price_update else avg_cost
        daily_change_percent = price_update.daily_change_percent if price_update else 0.0

        value = qty * current_price
        unrealized_pnl = (current_price - avg_cost) * qty
        pnl_percent = ((current_price - avg_cost) / avg_cost * 100) if avg_cost != 0 else 0.0

        positions.append(
            {
                "ticker": ticker,
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "value": value,
                "unrealized_pnl": unrealized_pnl,
                "pnl_percent": pnl_percent,
                "daily_change_percent": daily_change_percent,
            }
        )

    total_value = cash + sum(p["value"] for p in positions)

    return {
        "cash_balance": cash,
        "total_value": total_value,
        "positions": positions,
    }


@router.post("/portfolio/trade")
def post_trade(request: Request, body: TradeRequest) -> dict:
    """Execute a market order. Returns success status, error message if any, and trade details."""
    db_path: str = request.app.state.db_path
    cache = request.app.state.price_cache

    ticker = body.ticker
    price = cache.get_price(ticker)
    if price is None:
        raise HTTPException(status_code=400, detail=f"Price unavailable for {ticker}")

    result = execute_trade(db_path, ticker, body.side, body.quantity, price)

    if result["success"]:
        # Compute updated total value and save snapshot
        try:
            profile = get_user_profile(db_path)
            raw_positions = get_positions(db_path)
            cash = profile["cash_balance"]
            total = cash + sum(
                pos["quantity"] * (cache.get_price(pos["ticker"]) or pos["avg_cost"])
                for pos in raw_positions
            )
            save_portfolio_snapshot(db_path, total)
        except Exception:
            pass

        return {
            "success": True,
            "error": None,
            "cash_balance": result["cash_balance"],
            "trade": {
                "ticker": ticker,
                "side": body.side,
                "quantity": body.quantity,
                "price": price,
            },
        }

    return {
        "success": False,
        "error": result["error"],
        "cash_balance": result["cash_balance"],
        "trade": None,
    }


@router.get("/portfolio/history")
def get_history(request: Request) -> dict:
    """Return portfolio value history snapshots."""
    db_path: str = request.app.state.db_path
    history = get_portfolio_history(db_path)
    return {"history": history}
