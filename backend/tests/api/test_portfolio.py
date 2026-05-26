"""Tests for /api/portfolio routes."""

import sys
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock app.db before any router import
# ---------------------------------------------------------------------------

mock_db = MagicMock()
mock_db.DEFAULT_TICKERS = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
    "NVDA", "META", "JPM", "V", "NFLX",
]
sys.modules["app.db"] = mock_db

from app.routers.portfolio import router as portfolio_router  # noqa: E402

# Restore sys.modules so DB tests in other files import the real app.db module
sys.modules.pop("app.db", None)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_cache(prices: dict | None = None) -> MagicMock:
    """Return a MagicMock price cache with configurable per-ticker behaviour."""
    cache = MagicMock()
    prices = prices or {}

    def _get_price(ticker: str):
        return prices.get(ticker)

    def _get(ticker: str):
        p = prices.get(ticker)
        if p is None:
            return None
        update = MagicMock()
        update.price = p
        update.daily_change_percent = 1.5
        return update

    cache.get_price.side_effect = _get_price
    cache.get.side_effect = _get
    return cache


def make_test_app(state: dict) -> TestClient:
    app = FastAPI()
    app.include_router(portfolio_router, prefix="/api")
    for k, v in state.items():
        setattr(app.state, k, v)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/portfolio
# ---------------------------------------------------------------------------


def test_get_portfolio_shape_and_pnl():
    """Correct response shape and P&L calculation (price=192, avg_cost=190, qty=2)."""
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 5000.0, "created_at": "2024-01-01T00:00:00Z"}
    mock_db.get_positions.return_value = [
        {"ticker": "AAPL", "quantity": 2.0, "avg_cost": 190.0, "updated_at": "2024-01-01T00:00:00Z"}
    ]

    cache = make_mock_cache({"AAPL": 192.0})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()

    assert "cash_balance" in data
    assert "total_value" in data
    assert "positions" in data

    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert pos["quantity"] == 2.0
    assert pos["avg_cost"] == 190.0
    assert pos["current_price"] == 192.0
    assert pos["value"] == pytest.approx(384.0)
    assert pos["unrealized_pnl"] == pytest.approx(4.0)
    assert pos["pnl_percent"] == pytest.approx((2.0 / 190.0) * 100)
    assert "daily_change_percent" in pos

    assert data["total_value"] == pytest.approx(5000.0 + 384.0)


def test_get_portfolio_no_price_falls_back_to_avg_cost():
    """When price is unavailable in cache, fallback to avg_cost for current_price."""
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 1000.0, "created_at": "2024-01-01T00:00:00Z"}
    mock_db.get_positions.return_value = [
        {"ticker": "TSLA", "quantity": 1.0, "avg_cost": 250.0, "updated_at": "2024-01-01T00:00:00Z"}
    ]

    cache = make_mock_cache({})  # TSLA has no price
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()

    pos = data["positions"][0]
    assert pos["current_price"] == 250.0
    assert pos["unrealized_pnl"] == pytest.approx(0.0)
    assert pos["daily_change_percent"] == 0.0


def test_get_portfolio_empty_positions():
    """Empty positions list returns cash balance only."""
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 10000.0, "created_at": "2024-01-01T00:00:00Z"}
    mock_db.get_positions.return_value = []

    cache = make_mock_cache({})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert data["positions"] == []
    assert data["total_value"] == pytest.approx(10000.0)


# ---------------------------------------------------------------------------
# POST /api/portfolio/trade
# ---------------------------------------------------------------------------


def test_post_trade_buy_success():
    """Buy success returns success=True with trade info."""
    mock_db.execute_trade.return_value = {
        "success": True, "error": None, "cash_balance": 8000.0, "trade_id": "abc123"
    }
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 8000.0, "created_at": "2024-01-01T00:00:00Z"}
    mock_db.get_positions.return_value = []
    mock_db.save_portfolio_snapshot.return_value = None

    cache = make_mock_cache({"AAPL": 150.0})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10.0, "side": "buy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["error"] is None
    assert data["trade"]["ticker"] == "AAPL"
    assert data["trade"]["side"] == "buy"
    assert data["trade"]["quantity"] == 10.0
    assert data["trade"]["price"] == 150.0


def test_post_trade_price_unavailable():
    """Returns 400 when price is not in cache."""
    cache = make_mock_cache({})  # No prices available
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.post("/api/portfolio/trade", json={"ticker": "ZZZZ", "quantity": 1.0, "side": "buy"})
    assert resp.status_code == 400
    assert "Price unavailable" in resp.json()["detail"]


def test_post_trade_execute_failure():
    """When execute_trade returns failure, response has success=False with error."""
    mock_db.execute_trade.return_value = {
        "success": False,
        "error": "Insufficient cash to buy 1000 AAPL",
        "cash_balance": None,
        "trade_id": None,
    }

    cache = make_mock_cache({"AAPL": 200.0})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1000.0, "side": "buy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "Insufficient" in data["error"]
    assert data["trade"] is None


def test_post_trade_zero_quantity_rejected():
    """quantity=0 must be rejected with 422."""
    cache = make_mock_cache({"AAPL": 150.0})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 0, "side": "buy"})
    assert resp.status_code == 422


def test_post_trade_invalid_side_rejected():
    """Invalid side value must be rejected with 422."""
    cache = make_mock_cache({"AAPL": 150.0})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1.0, "side": "hold"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/portfolio/history
# ---------------------------------------------------------------------------


def test_get_portfolio_history():
    """Returns history list."""
    mock_db.get_portfolio_history.return_value = [
        {"total_value": 10000.0, "recorded_at": "2024-01-01T00:00:00Z"},
        {"total_value": 10500.0, "recorded_at": "2024-01-01T00:00:30Z"},
    ]

    cache = make_mock_cache({})
    client = make_test_app({"db_path": "test.db", "price_cache": cache})

    resp = client.get("/api/portfolio/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert len(data["history"]) == 2
    assert data["history"][0]["total_value"] == 10000.0
