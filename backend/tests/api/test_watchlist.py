"""Tests for /api/watchlist routes."""

import sys
from unittest.mock import AsyncMock, MagicMock

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

from app.routers.watchlist import router as watchlist_router  # noqa: E402

sys.modules.pop("app.db", None)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_market_source() -> MagicMock:
    source = MagicMock()
    source.add_ticker = AsyncMock()
    source.remove_ticker = AsyncMock()
    return source


def make_test_app(state: dict) -> TestClient:
    app = FastAPI()
    app.include_router(watchlist_router, prefix="/api")
    for k, v in state.items():
        setattr(app.state, k, v)
    return TestClient(app)


def default_state() -> dict:
    return {"db_path": "test.db", "market_source": make_mock_market_source()}


# ---------------------------------------------------------------------------
# GET /api/watchlist
# ---------------------------------------------------------------------------


def test_get_watchlist_returns_tickers():
    """GET /api/watchlist returns tickers list."""
    mock_db.get_watchlist.return_value = ["AAPL", "GOOGL", "MSFT"]
    client = make_test_app(default_state())

    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == {"tickers": ["AAPL", "GOOGL", "MSFT"]}


# ---------------------------------------------------------------------------
# POST /api/watchlist
# ---------------------------------------------------------------------------


def test_post_watchlist_success():
    """POST /api/watchlist with valid ticker returns 200 and the ticker."""
    mock_db.add_to_watchlist.return_value = None
    state = default_state()
    client = make_test_app(state)

    resp = client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "PYPL"}
    state["market_source"].add_ticker.assert_called_once_with("PYPL")


def test_post_watchlist_lowercase_normalized():
    """Lowercase ticker input is normalized to uppercase."""
    mock_db.add_to_watchlist.return_value = None
    state = default_state()
    client = make_test_app(state)

    resp = client.post("/api/watchlist", json={"ticker": "aapl"})
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"


def test_post_watchlist_duplicate_returns_409():
    """Duplicate ticker (ValueError from db) returns 409."""
    mock_db.add_to_watchlist.side_effect = ValueError("already in watchlist")
    client = make_test_app(default_state())

    resp = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert resp.status_code == 409
    assert "already in watchlist" in resp.json()["detail"].lower()

    # Reset side effect for subsequent tests
    mock_db.add_to_watchlist.side_effect = None


def test_post_watchlist_too_long_returns_422():
    """Ticker longer than 10 characters returns 422."""
    client = make_test_app(default_state())

    resp = client.post("/api/watchlist", json={"ticker": "TOOLONGTICKERX"})
    assert resp.status_code == 422


def test_post_watchlist_non_alphanumeric_returns_422():
    """Non-alphanumeric ticker returns 422."""
    client = make_test_app(default_state())

    resp = client.post("/api/watchlist", json={"ticker": "BRK.B"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/watchlist/{ticker}
# ---------------------------------------------------------------------------


def test_delete_watchlist_success():
    """DELETE /api/watchlist/AAPL returns 204 on success."""
    mock_db.remove_from_watchlist.return_value = None
    state = default_state()
    client = make_test_app(state)

    resp = client.delete("/api/watchlist/AAPL")
    assert resp.status_code == 204
    state["market_source"].remove_ticker.assert_called_once_with("AAPL")


def test_delete_watchlist_not_found_returns_404():
    """DELETE /api/watchlist/AAPL returns 404 when ticker is not in watchlist."""
    mock_db.remove_from_watchlist.side_effect = ValueError("not in watchlist")
    client = make_test_app(default_state())

    resp = client.delete("/api/watchlist/AAPL")
    assert resp.status_code == 404
    assert "not in watchlist" in resp.json()["detail"].lower()

    # Reset side effect
    mock_db.remove_from_watchlist.side_effect = None
