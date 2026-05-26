"""Tests for the LLM service and chat router.

app.db is mocked at the sys.modules level so tests don't require a real database.
LLM_MOCK=true is set before any app.llm imports so no real API calls are made.
"""

import os
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock app.db BEFORE importing any app.llm modules
# ---------------------------------------------------------------------------
mock_db = MagicMock()
sys.modules["app.db"] = mock_db

# Force mock LLM — must be set before importing service
os.environ["LLM_MOCK"] = "true"

# ---------------------------------------------------------------------------
# Now safe to import app.llm modules
# ---------------------------------------------------------------------------
from app.llm.schemas import LLMResponse, TradeAction, WatchlistChange  # noqa: E402
from app.llm.service import (  # noqa: E402
    build_messages,
    build_portfolio_context,
    call_llm,
    execute_llm_actions,
)

# Pre-import chat router while mock is still active so its from-app.db imports resolve to mock
import app.routers.chat  # noqa: E402, F401

# Restore sys.modules so DB tests in other files import the real app.db module
sys.modules.pop("app.db", None)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_price_cache(prices: dict[str, float]) -> MagicMock:
    """Create a fake PriceCache that returns prices from the given dict."""
    cache = MagicMock()
    cache.get_price.side_effect = lambda ticker: prices.get(ticker)
    return cache


def make_test_app(state_overrides: dict):
    """Create a minimal FastAPI app with the chat router mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers.chat import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    for k, v in state_overrides.items():
        setattr(app.state, k, v)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. call_llm with LLM_MOCK=true returns a valid LLMResponse
# ---------------------------------------------------------------------------


def test_call_llm_mock_returns_llm_response():
    messages = [{"role": "user", "content": "Hello"}]
    result = call_llm(messages)
    assert isinstance(result, LLMResponse)
    assert isinstance(result.message, str)
    assert len(result.message) > 0
    assert result.trades == []
    assert result.watchlist_changes == []


def test_call_llm_mock_message_content():
    """Mock response should contain the expected message."""
    messages = [{"role": "user", "content": "How is my portfolio?"}]
    result = call_llm(messages)
    assert "mock" in result.message.lower() or "finally" in result.message.lower()


# ---------------------------------------------------------------------------
# 2. build_portfolio_context includes cash balance and position info
# ---------------------------------------------------------------------------


def test_build_portfolio_context_includes_cash():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 8500.0}
    mock_db.get_positions.return_value = []
    mock_db.get_watchlist.return_value = []

    cache = make_price_cache({})
    context = build_portfolio_context("fake.db", cache)

    assert "8,500.00" in context or "8500" in context


def test_build_portfolio_context_includes_position():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 5000.0}
    mock_db.get_positions.return_value = [
        {"ticker": "AAPL", "quantity": 10, "avg_cost": 150.0}
    ]
    mock_db.get_watchlist.return_value = ["AAPL"]

    cache = make_price_cache({"AAPL": 160.0})
    context = build_portfolio_context("fake.db", cache)

    assert "AAPL" in context
    assert "10" in context
    assert "150" in context
    assert "160" in context


def test_build_portfolio_context_shows_unrealized_pnl():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 5000.0}
    mock_db.get_positions.return_value = [
        {"ticker": "TSLA", "quantity": 5, "avg_cost": 200.0}
    ]
    mock_db.get_watchlist.return_value = []

    # Price up — positive P&L
    cache = make_price_cache({"TSLA": 220.0})
    context = build_portfolio_context("fake.db", cache)

    assert "TSLA" in context
    # P&L = (220 - 200) * 5 = +100
    assert "+$100.00" in context or "100.00" in context


def test_build_portfolio_context_no_price_falls_back_to_avg_cost():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 5000.0}
    mock_db.get_positions.return_value = [
        {"ticker": "XYZ", "quantity": 2, "avg_cost": 50.0}
    ]
    mock_db.get_watchlist.return_value = []

    cache = make_price_cache({})  # No price for XYZ
    context = build_portfolio_context("fake.db", cache)

    assert "XYZ" in context
    assert "no live price" in context


def test_build_portfolio_context_watchlist_with_prices():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 10000.0}
    mock_db.get_positions.return_value = []
    mock_db.get_watchlist.return_value = ["AAPL", "MSFT"]

    cache = make_price_cache({"AAPL": 195.0, "MSFT": 380.0})
    context = build_portfolio_context("fake.db", cache)

    assert "AAPL" in context
    assert "MSFT" in context
    assert "195.00" in context
    assert "380.00" in context


# ---------------------------------------------------------------------------
# 3. build_messages: correct order — system, history, user
# ---------------------------------------------------------------------------


def test_build_messages_starts_with_system():
    messages = build_messages("hello", "Cash: $10000", [])
    assert messages[0]["role"] == "system"
    assert "FinAlly" in messages[0]["content"]


def test_build_messages_ends_with_user():
    messages = build_messages("What should I buy?", "Cash: $10000", [])
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "What should I buy?"


def test_build_messages_history_in_middle():
    history = [
        {"role": "user", "content": "Hi", "actions": None, "created_at": "2024-01-01"},
        {"role": "assistant", "content": "Hello!", "actions": None, "created_at": "2024-01-01"},
    ]
    messages = build_messages("New message", "Cash: $10000", history)

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hi"
    assert messages[2]["role"] == "assistant"
    assert messages[2]["content"] == "Hello!"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "New message"


def test_build_messages_portfolio_context_in_system():
    context = "Cash balance: $7,500.00\nTotal portfolio value: $12,000.00"
    messages = build_messages("hi", context, [])
    assert context in messages[0]["content"]


def test_build_messages_no_actions_field_in_history():
    """History messages should only have role/content — no actions leakage."""
    history = [
        {
            "role": "assistant",
            "content": "Bought 10 AAPL",
            "actions": {"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}]},
            "created_at": "2024-01-01",
        }
    ]
    messages = build_messages("thanks", "Cash: $5000", history)
    # The history message at index 1 should only have role and content
    hist_msg = messages[1]
    assert hist_msg["role"] == "assistant"
    assert hist_msg["content"] == "Bought 10 AAPL"
    assert "actions" not in hist_msg


# ---------------------------------------------------------------------------
# 4. execute_llm_actions: successful buy trade
# ---------------------------------------------------------------------------


def test_execute_llm_actions_successful_buy():
    mock_db.execute_trade.return_value = {
        "success": True,
        "error": None,
        "cash_balance": 8500.0,
        "trade_id": "abc123",
    }

    cache = make_price_cache({"AAPL": 150.0})
    llm_response = LLMResponse(
        message="Buying AAPL",
        trades=[TradeAction(ticker="AAPL", side="buy", quantity=10)],
        watchlist_changes=[],
    )

    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert errors == []
    assert len(executed) == 1
    assert executed[0]["type"] == "trade"
    assert executed[0]["ticker"] == "AAPL"
    assert executed[0]["side"] == "buy"
    assert executed[0]["quantity"] == 10
    assert executed[0]["price"] == 150.0

    mock_db.execute_trade.assert_called_once_with(
        "fake.db", "AAPL", "buy", 10, 150.0, user_id="default"
    )


# ---------------------------------------------------------------------------
# 5. execute_llm_actions: failed trade adds to errors
# ---------------------------------------------------------------------------


def test_execute_llm_actions_failed_trade_adds_error():
    mock_db.execute_trade.return_value = {
        "success": False,
        "error": "Insufficient cash to buy 1000 AAPL",
        "cash_balance": None,
        "trade_id": None,
    }

    cache = make_price_cache({"AAPL": 150.0})
    llm_response = LLMResponse(
        message="Buying AAPL",
        trades=[TradeAction(ticker="AAPL", side="buy", quantity=1000)],
        watchlist_changes=[],
    )

    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert len(errors) == 1
    assert "Insufficient cash" in errors[0]
    assert executed == []


# ---------------------------------------------------------------------------
# 6. execute_llm_actions: no price available adds to errors
# ---------------------------------------------------------------------------


def test_execute_llm_actions_no_price_adds_error():
    mock_db.execute_trade.reset_mock()

    cache = make_price_cache({})  # No prices at all

    llm_response = LLMResponse(
        message="Buying ZZZZ",
        trades=[TradeAction(ticker="ZZZZ", side="buy", quantity=5)],
        watchlist_changes=[],
    )

    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert len(errors) == 1
    assert "ZZZZ" in errors[0]
    assert "No price available" in errors[0]
    assert executed == []
    mock_db.execute_trade.assert_not_called()


# ---------------------------------------------------------------------------
# 7. execute_llm_actions: watchlist add/remove executed
# ---------------------------------------------------------------------------


def test_execute_llm_actions_watchlist_add():
    mock_db.add_to_watchlist.return_value = None

    cache = make_price_cache({})
    llm_response = LLMResponse(
        message="Added PYPL",
        trades=[],
        watchlist_changes=[WatchlistChange(ticker="pypl", action="add")],
    )

    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert errors == []
    assert len(executed) == 1
    assert executed[0]["type"] == "watchlist"
    assert executed[0]["ticker"] == "PYPL"  # normalized to uppercase
    assert executed[0]["action"] == "add"
    mock_db.add_to_watchlist.assert_called_once_with("fake.db", "PYPL", user_id="default")


def test_execute_llm_actions_watchlist_remove():
    mock_db.remove_from_watchlist.return_value = None

    cache = make_price_cache({})
    llm_response = LLMResponse(
        message="Removed NFLX",
        trades=[],
        watchlist_changes=[WatchlistChange(ticker="nflx", action="remove")],
    )

    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert errors == []
    assert len(executed) == 1
    assert executed[0]["ticker"] == "NFLX"
    assert executed[0]["action"] == "remove"
    mock_db.remove_from_watchlist.assert_called_once_with("fake.db", "NFLX", user_id="default")


# ---------------------------------------------------------------------------
# 8. execute_llm_actions: watchlist add ValueError ignored
# ---------------------------------------------------------------------------


def test_execute_llm_actions_watchlist_add_already_present_ignored():
    mock_db.add_to_watchlist.side_effect = ValueError("already in watchlist")

    cache = make_price_cache({})
    llm_response = LLMResponse(
        message="Adding AAPL",
        trades=[],
        watchlist_changes=[WatchlistChange(ticker="AAPL", action="add")],
    )

    # Should not raise — ValueError is silently ignored
    executed, errors = execute_llm_actions("fake.db", cache, llm_response)

    assert errors == []
    # The watchlist action is still recorded in executed_actions even if it was a duplicate
    assert any(a["type"] == "watchlist" and a["ticker"] == "AAPL" for a in executed)

    # Reset side_effect for subsequent tests
    mock_db.add_to_watchlist.side_effect = None


# ---------------------------------------------------------------------------
# 9. POST /api/chat returns correct response shape
# ---------------------------------------------------------------------------


def test_chat_endpoint_response_shape():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 10000.0}
    mock_db.get_positions.return_value = []
    mock_db.get_watchlist.return_value = ["AAPL"]
    mock_db.get_chat_messages.return_value = []
    mock_db.save_chat_message.return_value = "msg-id-001"

    cache = make_price_cache({"AAPL": 190.0})
    client = make_test_app({"price_cache": cache, "db_path": "fake.db"})

    response = client.post("/api/chat", json={"message": "Hello FinAlly"})

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "trades" in data
    assert "watchlist_changes" in data
    assert "errors" in data
    assert isinstance(data["message"], str)
    assert isinstance(data["trades"], list)
    assert isinstance(data["watchlist_changes"], list)
    assert isinstance(data["errors"], list)


def test_chat_endpoint_mock_message_content():
    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 10000.0}
    mock_db.get_positions.return_value = []
    mock_db.get_watchlist.return_value = []
    mock_db.get_chat_messages.return_value = []
    mock_db.save_chat_message.return_value = "msg-id-002"

    cache = make_price_cache({})
    client = make_test_app({"price_cache": cache, "db_path": "fake.db"})

    response = client.post("/api/chat", json={"message": "What do you think?"})

    assert response.status_code == 200
    data = response.json()
    # Mock message should mention "mock" or "FinAlly"
    assert "mock" in data["message"].lower() or "finally" in data["message"].lower()


# ---------------------------------------------------------------------------
# 10. POST /api/chat: executed trade appears in response
# ---------------------------------------------------------------------------


def test_chat_endpoint_executed_trade_in_response():
    """When the mock LLM response includes trades, they appear in the API response."""
    from unittest.mock import patch

    mock_db.get_user_profile.return_value = {"id": "default", "cash_balance": 10000.0}
    mock_db.get_positions.return_value = []
    mock_db.get_watchlist.return_value = []
    mock_db.get_chat_messages.return_value = []
    mock_db.save_chat_message.return_value = "msg-id-003"
    mock_db.execute_trade.return_value = {
        "success": True,
        "error": None,
        "cash_balance": 8500.0,
        "trade_id": "trade-001",
    }

    cache = make_price_cache({"AAPL": 150.0})

    # Patch call_llm to return a response with a trade action
    mock_llm_response = LLMResponse(
        message="I'll buy 10 shares of AAPL for you.",
        trades=[TradeAction(ticker="AAPL", side="buy", quantity=10)],
        watchlist_changes=[],
    )

    with patch("app.routers.chat.call_llm", return_value=mock_llm_response):
        client = make_test_app({"price_cache": cache, "db_path": "fake.db"})
        response = client.post("/api/chat", json={"message": "Buy 10 AAPL"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["trades"]) == 1
    assert data["trades"][0]["ticker"] == "AAPL"
    assert data["trades"][0]["side"] == "buy"
    assert data["trades"][0]["quantity"] == 10
    assert data["errors"] == []
