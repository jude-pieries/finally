"""Database module for FinAlly — SQLite-backed persistence layer.

All public functions open their own connection, execute, commit, and close.
WAL mode and row_factory are enabled on every connection.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Module-level constants — imported by other agents/modules
# ---------------------------------------------------------------------------

DEFAULT_USER_ID = "default"
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
DEFAULT_CASH = 10000.0

_SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "schema.sql"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with WAL mode and dict-friendly row_factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    """Return current UTC time as ISO 8601 string with trailing Z."""
    return datetime.utcnow().isoformat() + "Z"


def _new_id() -> str:
    """Return a new UUID as a 32-char hex string."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db(db_path: str) -> None:
    """Create tables from schema.sql and seed default data.

    Creates the parent directory of db_path if it doesn't exist.
    Safe to call multiple times — seed inserts use OR IGNORE.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    schema_sql = _SCHEMA_PATH.read_text()

    conn = _connect(db_path)
    try:
        conn.executescript(schema_sql)

        # Seed default user profile (skip if already present)
        conn.execute(
            "INSERT OR IGNORE INTO user_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, DEFAULT_CASH, _now()),
        )

        # Seed default watchlist tickers
        for ticker in DEFAULT_TICKERS:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                (_new_id(), DEFAULT_USER_ID, ticker, _now()),
            )

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


def get_user_profile(db_path: str, user_id: str = DEFAULT_USER_ID) -> dict:
    """Return the user profile as a dict with keys: id, cash_balance, created_at."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, cash_balance, created_at FROM user_profile WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"User profile not found: {user_id}")
        return dict(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def get_positions(db_path: str, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """Return all open positions as a list of dicts with keys: ticker, quantity, avg_cost, updated_at."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Trade execution
# ---------------------------------------------------------------------------


def execute_trade(
    db_path: str,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Execute a market order atomically.

    Returns a dict:
      {'success': bool, 'error': str|None, 'cash_balance': float|None, 'trade_id': str|None}
    """
    conn = _connect(db_path)
    try:
        with conn:
            profile = conn.execute(
                "SELECT cash_balance FROM user_profile WHERE id = ?",
                (user_id,),
            ).fetchone()
            if profile is None:
                return {"success": False, "error": f"User not found: {user_id}", "cash_balance": None, "trade_id": None}

            cash_balance = profile["cash_balance"]

            if side == "buy":
                cost = price * quantity
                if cash_balance < cost:
                    return {
                        "success": False,
                        "error": f"Insufficient cash to buy {quantity} {ticker}",
                        "cash_balance": None,
                        "trade_id": None,
                    }

                new_balance = cash_balance - cost

                # Upsert position
                existing = conn.execute(
                    "SELECT quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
                    (user_id, ticker),
                ).fetchone()

                now = _now()
                if existing:
                    old_qty = existing["quantity"]
                    old_avg = existing["avg_cost"]
                    new_qty = old_qty + quantity
                    new_avg = (old_qty * old_avg + quantity * price) / new_qty
                    conn.execute(
                        "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? "
                        "WHERE user_id = ? AND ticker = ?",
                        (new_qty, new_avg, now, user_id, ticker),
                    )
                else:
                    conn.execute(
                        "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (_new_id(), user_id, ticker, quantity, price, now),
                    )

            elif side == "sell":
                existing = conn.execute(
                    "SELECT quantity FROM positions WHERE user_id = ? AND ticker = ?",
                    (user_id, ticker),
                ).fetchone()

                if existing is None:
                    return {
                        "success": False,
                        "error": f"No position in {ticker}",
                        "cash_balance": None,
                        "trade_id": None,
                    }

                if existing["quantity"] < quantity:
                    return {
                        "success": False,
                        "error": f"Insufficient shares in {ticker}",
                        "cash_balance": None,
                        "trade_id": None,
                    }

                proceeds = price * quantity
                new_balance = cash_balance + proceeds
                new_qty = existing["quantity"] - quantity

                now = _now()
                if new_qty == 0:
                    conn.execute(
                        "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                        (user_id, ticker),
                    )
                else:
                    conn.execute(
                        "UPDATE positions SET quantity = ?, updated_at = ? "
                        "WHERE user_id = ? AND ticker = ?",
                        (new_qty, now, user_id, ticker),
                    )

            else:
                return {
                    "success": False,
                    "error": f"Invalid side: {side}",
                    "cash_balance": None,
                    "trade_id": None,
                }

            # Update cash balance
            conn.execute(
                "UPDATE user_profile SET cash_balance = ? WHERE id = ?",
                (new_balance, user_id),
            )

            # Record trade
            trade_id = _new_id()
            conn.execute(
                "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trade_id, user_id, ticker, side, quantity, price, _now()),
            )

        return {"success": True, "error": None, "cash_balance": new_balance, "trade_id": trade_id}

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


def get_watchlist(db_path: str, user_id: str = DEFAULT_USER_ID) -> list[str]:
    """Return tickers in the watchlist ordered by added_at ASC."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at ASC",
            (user_id,),
        ).fetchall()
        return [row["ticker"] for row in rows]
    finally:
        conn.close()


def add_to_watchlist(db_path: str, ticker: str, user_id: str = DEFAULT_USER_ID) -> None:
    """Add a ticker to the watchlist.

    Raises ValueError('already in watchlist') if the ticker is already present.
    """
    conn = _connect(db_path)
    try:
        try:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                (_new_id(), user_id, ticker, _now()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("already in watchlist")
    finally:
        conn.close()


def remove_from_watchlist(db_path: str, ticker: str, user_id: str = DEFAULT_USER_ID) -> None:
    """Remove a ticker from the watchlist.

    Raises ValueError('not in watchlist') if the ticker was not present.
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError("not in watchlist")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Portfolio snapshots
# ---------------------------------------------------------------------------


def save_portfolio_snapshot(
    db_path: str, total_value: float, user_id: str = DEFAULT_USER_ID
) -> None:
    """Insert a portfolio value snapshot."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
            (_new_id(), user_id, total_value, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_portfolio_history(db_path: str, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """Return all portfolio snapshots ordered by recorded_at ASC.

    Each dict has keys: total_value, recorded_at.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots "
            "WHERE user_id = ? ORDER BY recorded_at ASC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------


def get_chat_messages(
    db_path: str, user_id: str = DEFAULT_USER_ID, limit: int = 20
) -> list[dict]:
    """Return the last `limit` messages in chronological order (oldest first).

    Each dict has keys: role, content, actions (deserialized dict or None), created_at.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT role, content, actions, created_at FROM chat_messages "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        # Reverse so oldest-first
        messages = []
        for row in reversed(rows):
            msg = dict(row)
            if msg["actions"] is not None:
                msg["actions"] = json.loads(msg["actions"])
            messages.append(msg)
        return messages
    finally:
        conn.close()


def save_chat_message(
    db_path: str,
    role: str,
    content: str,
    actions: dict | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> str:
    """Save a chat message and return its id.

    actions dict is serialized to a JSON string for storage.
    """
    msg_id = _new_id()
    actions_json = json.dumps(actions) if actions is not None else None
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, user_id, role, content, actions_json, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return msg_id
