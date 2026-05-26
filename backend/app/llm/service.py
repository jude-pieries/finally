"""LLM service layer — portfolio context, message building, LiteLLM calls, action execution."""

import os

from dotenv import load_dotenv
from litellm import completion

from app.db import (
    add_to_watchlist,
    execute_trade,
    get_positions,
    get_user_profile,
    get_watchlist,
    remove_from_watchlist,
)
from app.llm.schemas import LLMResponse

load_dotenv()

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

SYSTEM_PROMPT_TEMPLATE = (
    "You are FinAlly, an AI trading assistant for a simulated portfolio with $10,000 virtual money.\n"
    "Help users analyze their portfolio, suggest and execute trades, and manage their watchlist.\n"
    "Be concise and data-driven. Execute trades only when explicitly asked or clearly agreed to.\n"
    "Respond ONLY with valid JSON matching the required schema — no extra text.\n"
    "\n"
    "Current portfolio:\n"
    "{portfolio_context}"
)


def build_portfolio_context(
    db_path: str,
    price_cache: object,
    user_id: str = "default",
) -> str:
    """Build a human-readable text summary of the user's portfolio for the system prompt."""
    profile = get_user_profile(db_path, user_id=user_id)
    positions = get_positions(db_path, user_id=user_id)
    watchlist = get_watchlist(db_path, user_id=user_id)

    cash = profile["cash_balance"]

    # Calculate total portfolio value
    position_value = 0.0
    for pos in positions:
        price = price_cache.get_price(pos["ticker"])
        if price is not None:
            position_value += pos["quantity"] * price
        else:
            # Fall back to average cost if price not available
            position_value += pos["quantity"] * pos["avg_cost"]

    total_value = cash + position_value

    lines = [
        f"Cash balance: ${cash:,.2f}",
        f"Total portfolio value: ${total_value:,.2f}",
        "",
        "Positions:",
    ]

    if positions:
        for pos in positions:
            ticker = pos["ticker"]
            qty = pos["quantity"]
            avg_cost = pos["avg_cost"]
            current_price = price_cache.get_price(ticker)
            if current_price is not None:
                unrealized_pnl = (current_price - avg_cost) * qty
                pnl_sign = "+" if unrealized_pnl >= 0 else ""
                lines.append(
                    f"  {ticker}: {qty} shares @ avg ${avg_cost:.2f}, "
                    f"current ${current_price:.2f}, "
                    f"P&L {pnl_sign}${unrealized_pnl:,.2f}"
                )
            else:
                lines.append(
                    f"  {ticker}: {qty} shares @ avg ${avg_cost:.2f} (no live price)"
                )
    else:
        lines.append("  (no open positions)")

    lines.append("")
    lines.append("Watchlist:")

    if watchlist:
        watchlist_parts = []
        for ticker in watchlist:
            price = price_cache.get_price(ticker)
            if price is not None:
                watchlist_parts.append(f"{ticker} (${price:.2f})")
            else:
                watchlist_parts.append(ticker)
        lines.append("  " + ", ".join(watchlist_parts))
    else:
        lines.append("  (empty)")

    return "\n".join(lines)


def build_messages(
    user_message: str,
    portfolio_context: str,
    history: list[dict],
) -> list[dict]:
    """Build the messages list for the LLM API call.

    Returns [system_message, ...history_messages, user_message].
    """
    system_content = SYSTEM_PROMPT_TEMPLATE.format(portfolio_context=portfolio_context)

    messages: list[dict] = [{"role": "system", "content": system_content}]

    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    return messages


def call_llm(messages: list[dict]) -> LLMResponse:
    """Call the LLM and return a parsed LLMResponse.

    If LLM_MOCK env var is "true" (case-insensitive), returns a deterministic mock response.
    Raises RuntimeError on LiteLLM failure.
    """
    if os.getenv("LLM_MOCK", "false").lower() == "true":
        return LLMResponse(
            message="This is a mock response from FinAlly. Portfolio looks good!",
            trades=[],
            watchlist_changes=[],
        )

    # --- SSL NOTE (dev workaround) ---
    # ssl_verify=False disables certificate verification on the outbound HTTPS call to
    # OpenRouter. This is required when running behind a corporate SSL-inspection proxy
    # (e.g. Zscaler), which re-signs TLS certificates with a private corporate CA that
    # the Docker container does not trust by default.
    #
    # Traffic is still encrypted end-to-end — ssl_verify=False only skips the check
    # that the certificate is signed by a trusted CA. The risk in a local dev environment
    # is negligible.
    #
    # ⚠️  TODO BEFORE GO-LIVE — remove this workaround and do one of the following:
    #   Option A (recommended): Inject the corporate root CA into the Docker image so
    #     verification passes properly:
    #       1. Export the Zscaler root cert from macOS Keychain as a .pem file.
    #       2. Add to Dockerfile:
    #            COPY zscaler-root.pem /usr/local/share/ca-certificates/zscaler.crt
    #            RUN update-ca-certificates
    #       3. Set in .env:  REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    #       4. Remove ssl_verify=False below and the ssl_verify variable entirely.
    #   Option B: Deploy to an environment (cloud/CI) that does not intercept TLS, in
    #     which case standard certificate verification will succeed without any changes.
    # ---------------------------------
    # False in all non-production environments (disables cert check to work behind Zscaler).
    # Set ENVIRONMENT=production to re-enable full SSL verification on deployment.
    ssl_verify = os.getenv("ENVIRONMENT", "development") == "production"

    try:
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            ssl_verify=ssl_verify,
        )
        raw_content = response.choices[0].message.content
        # Handle both JSON string and dict content
        if isinstance(raw_content, str):
            return LLMResponse.model_validate_json(raw_content)
        return LLMResponse.model_validate(raw_content)
    except Exception as exc:
        raise RuntimeError(f"LLM call failed: {exc}") from exc


def execute_llm_actions(
    db_path: str,
    price_cache: object,
    llm_response: LLMResponse,
    user_id: str = "default",
) -> tuple[list[dict], list[str]]:
    """Execute trades and watchlist changes from the LLM response.

    Returns (executed_actions, errors).
    - executed_actions: list of dicts describing completed actions
    - errors: list of error strings for failed trades
    """
    executed_actions: list[dict] = []
    errors: list[str] = []

    for trade in llm_response.trades:
        ticker = trade.ticker.upper()
        side = trade.side
        quantity = trade.quantity

        price = price_cache.get_price(ticker)
        if price is None:
            errors.append(f"No price available for {ticker}")
            continue

        result = execute_trade(db_path, ticker, side, quantity, price, user_id=user_id)
        if result["success"]:
            executed_actions.append(
                {
                    "type": "trade",
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                }
            )
        else:
            errors.append(result["error"])

    for change in llm_response.watchlist_changes:
        ticker = change.ticker.upper()
        action = change.action

        if action == "add":
            try:
                add_to_watchlist(db_path, ticker, user_id=user_id)
            except ValueError:
                pass  # Already present — ignore
        elif action == "remove":
            try:
                remove_from_watchlist(db_path, ticker, user_id=user_id)
            except ValueError:
                pass  # Not found — ignore

        executed_actions.append({"type": "watchlist", "ticker": ticker, "action": action})

    return executed_actions, errors
