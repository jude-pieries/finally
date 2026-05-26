"""Chat router — POST /api/chat endpoint for LLM-powered assistant."""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.db import get_chat_messages, save_chat_message
from app.llm.service import (
    build_messages,
    build_portfolio_context,
    call_llm,
    execute_llm_actions,
)

router = APIRouter()

DB_PATH = os.getenv("DB_PATH", "db/finally.db")


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Send a user message to the AI assistant and receive a structured response.

    The assistant may execute trades and watchlist changes automatically.
    Returns: {message, trades, watchlist_changes, errors}
    """
    price_cache = request.app.state.price_cache
    db_path = request.app.state.db_path

    # 1. Build portfolio context for system prompt
    portfolio_context = build_portfolio_context(db_path, price_cache)

    # 2. Load conversation history (last 20 messages)
    history = get_chat_messages(db_path, limit=20)

    # 3. Build LLM messages array
    messages = build_messages(body.message, portfolio_context, history)

    # 4. Call LLM (or mock)
    try:
        llm_response = call_llm(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    # 5. Execute trades and watchlist changes
    executed_actions, errors = execute_llm_actions(db_path, price_cache, llm_response)

    # 6. Save user message
    save_chat_message(db_path, "user", body.message, actions=None)

    # 7. Save assistant response with actions taken
    actions_payload = (
        {
            "trades": [t.model_dump() for t in llm_response.trades],
            "watchlist_changes": [w.model_dump() for w in llm_response.watchlist_changes],
            "executed": executed_actions,
            "errors": errors,
        }
        if (executed_actions or errors)
        else None
    )
    save_chat_message(
        db_path,
        "assistant",
        llm_response.message,
        actions=actions_payload,
    )

    # 8. Return response
    return {
        "message": llm_response.message,
        "trades": [t.model_dump() for t in llm_response.trades],
        "watchlist_changes": [w.model_dump() for w in llm_response.watchlist_changes],
        "errors": errors,
    }
