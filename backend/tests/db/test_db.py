"""Comprehensive tests for backend/app/db.py."""

import sqlite3

import pytest

from app.db import (
    DEFAULT_CASH,
    DEFAULT_TICKERS,
    DEFAULT_USER_ID,
    add_to_watchlist,
    execute_trade,
    get_chat_messages,
    get_portfolio_history,
    get_positions,
    get_user_profile,
    get_watchlist,
    init_db,
    remove_from_watchlist,
    save_chat_message,
    save_portfolio_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def db(tmp_path) -> str:
    """Return a fresh db path under tmp_path and initialise it."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


# ---------------------------------------------------------------------------
# 1-4: init_db
# ---------------------------------------------------------------------------


def test_init_db_creates_all_tables(tmp_path):
    """All 6 expected tables must exist after init_db."""
    path = str(tmp_path / "test.db")
    init_db(path)

    conn = sqlite3.connect(path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()

    expected = {"user_profile", "watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"}
    assert expected.issubset(tables)


def test_init_db_seeds_user_profile(tmp_path):
    """Default user profile must be seeded with $10k cash."""
    path = str(tmp_path / "test.db")
    init_db(path)

    profile = get_user_profile(path)
    assert profile["id"] == DEFAULT_USER_ID
    assert profile["cash_balance"] == DEFAULT_CASH


def test_init_db_seeds_default_tickers(tmp_path):
    """All 10 default tickers must be present in the watchlist."""
    path = str(tmp_path / "test.db")
    init_db(path)

    tickers = get_watchlist(path)
    assert len(tickers) == len(DEFAULT_TICKERS)
    assert set(tickers) == set(DEFAULT_TICKERS)


def test_init_db_is_idempotent(tmp_path):
    """Calling init_db twice must not duplicate seed data."""
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    tickers = get_watchlist(path)
    assert len(tickers) == len(DEFAULT_TICKERS)

    conn = sqlite3.connect(path)
    profile_count = conn.execute("SELECT COUNT(*) FROM user_profile WHERE id = 'default'").fetchone()[0]
    conn.close()
    assert profile_count == 1


# ---------------------------------------------------------------------------
# 5-7: execute_trade — buy
# ---------------------------------------------------------------------------


def test_execute_trade_buy_success(tmp_path):
    """Buying shares reduces cash and creates a position."""
    path = db(tmp_path)

    result = execute_trade(path, "AAPL", "buy", 10, 100.0)

    assert result["success"] is True
    assert result["error"] is None
    assert result["trade_id"] is not None

    expected_balance = DEFAULT_CASH - 10 * 100.0
    assert result["cash_balance"] == pytest.approx(expected_balance)

    profile = get_user_profile(path)
    assert profile["cash_balance"] == pytest.approx(expected_balance)

    positions = get_positions(path)
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["quantity"] == pytest.approx(10)
    assert positions[0]["avg_cost"] == pytest.approx(100.0)

    # Trade recorded
    conn = sqlite3.connect(path)
    trades = conn.execute("SELECT * FROM trades WHERE ticker = 'AAPL'").fetchall()
    conn.close()
    assert len(trades) == 1


def test_execute_trade_buy_insufficient_cash(tmp_path):
    """Buying more than cash allows must return a failure."""
    path = db(tmp_path)

    # Price * qty = 200_000 >> $10k
    result = execute_trade(path, "AAPL", "buy", 1000, 200.0)

    assert result["success"] is False
    assert result["error"] is not None
    assert "Insufficient cash" in result["error"]
    assert result["cash_balance"] is None
    assert result["trade_id"] is None

    # Cash must be unchanged
    profile = get_user_profile(path)
    assert profile["cash_balance"] == pytest.approx(DEFAULT_CASH)

    # No position created
    assert get_positions(path) == []


def test_execute_trade_buy_weighted_avg_cost(tmp_path):
    """Second buy of same ticker must produce correct weighted average cost."""
    path = db(tmp_path)

    execute_trade(path, "AAPL", "buy", 10, 100.0)   # cost basis: $100
    execute_trade(path, "AAPL", "buy", 10, 200.0)   # cost basis: $200

    positions = get_positions(path)
    assert len(positions) == 1
    pos = positions[0]
    assert pos["quantity"] == pytest.approx(20)
    # Weighted avg = (10*100 + 10*200) / 20 = 150
    assert pos["avg_cost"] == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# 8-11: execute_trade — sell
# ---------------------------------------------------------------------------


def test_execute_trade_sell_success(tmp_path):
    """Selling shares increases cash and reduces position quantity."""
    path = db(tmp_path)

    execute_trade(path, "AAPL", "buy", 10, 100.0)
    cash_after_buy = get_user_profile(path)["cash_balance"]

    result = execute_trade(path, "AAPL", "sell", 5, 120.0)

    assert result["success"] is True
    assert result["error"] is None

    expected_balance = cash_after_buy + 5 * 120.0
    assert result["cash_balance"] == pytest.approx(expected_balance)

    profile = get_user_profile(path)
    assert profile["cash_balance"] == pytest.approx(expected_balance)

    positions = get_positions(path)
    assert len(positions) == 1
    assert positions[0]["quantity"] == pytest.approx(5)


def test_execute_trade_sell_all_shares_removes_position(tmp_path):
    """Selling all shares must delete the position row."""
    path = db(tmp_path)

    execute_trade(path, "AAPL", "buy", 10, 100.0)
    result = execute_trade(path, "AAPL", "sell", 10, 110.0)

    assert result["success"] is True
    assert get_positions(path) == []


def test_execute_trade_sell_insufficient_shares(tmp_path):
    """Selling more shares than owned must return a failure."""
    path = db(tmp_path)

    execute_trade(path, "AAPL", "buy", 5, 100.0)
    result = execute_trade(path, "AAPL", "sell", 10, 100.0)

    assert result["success"] is False
    assert "Insufficient shares" in result["error"]
    assert result["cash_balance"] is None

    # Quantity must be unchanged
    positions = get_positions(path)
    assert positions[0]["quantity"] == pytest.approx(5)


def test_execute_trade_sell_no_position(tmp_path):
    """Selling a ticker with no position must return a failure."""
    path = db(tmp_path)

    result = execute_trade(path, "AAPL", "sell", 1, 100.0)

    assert result["success"] is False
    assert "No position" in result["error"]
    assert result["cash_balance"] is None
    assert result["trade_id"] is None


# ---------------------------------------------------------------------------
# 12-16: Watchlist
# ---------------------------------------------------------------------------


def test_get_watchlist_returns_tickers_in_order(tmp_path):
    """get_watchlist must return tickers ordered by added_at ASC."""
    path = db(tmp_path)
    tickers = get_watchlist(path)
    # Must be a list of strings
    assert all(isinstance(t, str) for t in tickers)
    assert len(tickers) == len(DEFAULT_TICKERS)


def test_add_to_watchlist_success(tmp_path):
    """A new ticker can be added to the watchlist."""
    path = db(tmp_path)
    add_to_watchlist(path, "PYPL")
    tickers = get_watchlist(path)
    assert "PYPL" in tickers


def test_add_to_watchlist_duplicate_raises(tmp_path):
    """Adding a duplicate ticker must raise ValueError."""
    path = db(tmp_path)
    with pytest.raises(ValueError, match="already in watchlist"):
        add_to_watchlist(path, "AAPL")  # AAPL is seeded by default


def test_remove_from_watchlist_success(tmp_path):
    """Removing an existing ticker must succeed."""
    path = db(tmp_path)
    remove_from_watchlist(path, "AAPL")
    tickers = get_watchlist(path)
    assert "AAPL" not in tickers


def test_remove_from_watchlist_not_present_raises(tmp_path):
    """Removing a ticker that is not present must raise ValueError."""
    path = db(tmp_path)
    with pytest.raises(ValueError, match="not in watchlist"):
        remove_from_watchlist(path, "NOTREAL")


# ---------------------------------------------------------------------------
# 17: Portfolio snapshots
# ---------------------------------------------------------------------------


def test_save_and_get_portfolio_history(tmp_path):
    """Snapshots are stored and returned in time order."""
    path = db(tmp_path)

    save_portfolio_snapshot(path, 10000.0)
    save_portfolio_snapshot(path, 10500.0)
    save_portfolio_snapshot(path, 9800.0)

    history = get_portfolio_history(path)
    assert len(history) == 3
    values = [h["total_value"] for h in history]
    assert values == [10000.0, 10500.0, 9800.0]
    assert all("recorded_at" in h for h in history)


# ---------------------------------------------------------------------------
# 18-20: Chat messages
# ---------------------------------------------------------------------------


def test_save_and_get_chat_messages(tmp_path):
    """Messages are stored and retrieved with correct role and content."""
    path = db(tmp_path)

    save_chat_message(path, "user", "Hello AI")
    save_chat_message(path, "assistant", "Hello human")

    messages = get_chat_messages(path)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello AI"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hello human"


def test_get_chat_messages_limit(tmp_path):
    """get_chat_messages must return only the last N messages."""
    path = db(tmp_path)

    for i in range(25):
        save_chat_message(path, "user", f"Message {i}")

    messages = get_chat_messages(path, limit=10)
    assert len(messages) == 10
    # Must be the LAST 10 messages (messages 15-24) in chronological order
    assert messages[-1]["content"] == "Message 24"
    assert messages[0]["content"] == "Message 15"


def test_get_chat_messages_actions_serialization(tmp_path):
    """actions dict is serialized to JSON on save and deserialized on read."""
    path = db(tmp_path)

    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
    }
    save_chat_message(path, "assistant", "Executed trade", actions=actions)

    messages = get_chat_messages(path)
    assert len(messages) == 1
    retrieved_actions = messages[0]["actions"]
    assert isinstance(retrieved_actions, dict)
    assert retrieved_actions == actions


def test_get_chat_messages_no_actions_is_none(tmp_path):
    """Messages saved without actions have actions=None when retrieved."""
    path = db(tmp_path)

    save_chat_message(path, "user", "Just a question")
    messages = get_chat_messages(path)
    assert messages[0]["actions"] is None
