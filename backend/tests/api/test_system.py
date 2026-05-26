"""Tests for /api/health route."""

import sys
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock app.db before any router import (defensive — system.py doesn't use db,
# but may be imported alongside other routers that do)
# ---------------------------------------------------------------------------

mock_db = MagicMock()
mock_db.DEFAULT_TICKERS = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
    "NVDA", "META", "JPM", "V", "NFLX",
]
sys.modules["app.db"] = mock_db

from app.routers.system import router as system_router  # noqa: E402

sys.modules.pop("app.db", None)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_test_app(state: dict) -> TestClient:
    app = FastAPI()
    app.include_router(system_router, prefix="/api")
    for k, v in state.items():
        setattr(app.state, k, v)
    return TestClient(app)


def make_mock_market_source(tickers: list[str] | None = None) -> MagicMock:
    source = MagicMock()
    source.get_tickers.return_value = tickers or []
    return source


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


def test_health_check_ok(monkeypatch):
    """GET /api/health returns status ok."""
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    source = make_mock_market_source(["AAPL", "GOOGL", "MSFT"])
    client = make_test_app({"market_source": source})

    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["market_data"] == "simulator"
    assert data["tickers"] == 3


def test_health_check_massive_mode(monkeypatch):
    """When MASSIVE_API_KEY is set, market_data reports 'massive'."""
    monkeypatch.setenv("MASSIVE_API_KEY", "test-api-key")
    source = make_mock_market_source(["AAPL"])
    client = make_test_app({"market_source": source})

    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["market_data"] == "massive"
    assert data["tickers"] == 1
