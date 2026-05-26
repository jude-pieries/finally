"""FinAlly FastAPI application entry point."""

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import (
    DEFAULT_TICKERS,
    get_positions,
    get_user_profile,
    get_watchlist,
    init_db,
    save_portfolio_snapshot,
)
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.routers import portfolio, prices, system, watchlist

load_dotenv()  # Load .env from CWD (project root in Docker, backend/ in local dev)

DB_PATH = os.getenv("DB_PATH", "db/finally.db")
STATIC_DIR = os.getenv("STATIC_DIR", "static")

price_cache = PriceCache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize DB, start market data, run snapshot loop."""
    # Ensure DB directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Init DB (creates schema + seeds if fresh)
    init_db(DB_PATH)

    # Get initial watchlist; fall back to defaults if empty
    tickers = get_watchlist(DB_PATH) or DEFAULT_TICKERS

    # Start market data source
    market_source = create_market_data_source(price_cache)
    await market_source.start(tickers)

    # Store in app.state for access by route handlers
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    app.state.db_path = DB_PATH

    # Start portfolio snapshot background task (every 30 seconds)
    snapshot_task = asyncio.create_task(_snapshot_loop(DB_PATH, price_cache))

    yield

    snapshot_task.cancel()
    try:
        await snapshot_task
    except asyncio.CancelledError:
        pass
    await market_source.stop()


async def _snapshot_loop(db_path: str, cache: PriceCache) -> None:
    """Background task: save portfolio value snapshot every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            profile = get_user_profile(db_path)
            positions = get_positions(db_path)
            cash = profile["cash_balance"]
            total = cash + sum(
                pos["quantity"] * (cache.get_price(pos["ticker"]) or pos["avg_cost"])
                for pos in positions
            )
            save_portfolio_snapshot(db_path, total)
        except Exception:
            pass


app = FastAPI(title="FinAlly API", lifespan=lifespan)

# CORS for local development (frontend on :3000, backend on :8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# SSE streaming (prefix already embedded in the router: /api/stream/prices)
app.include_router(create_stream_router(price_cache))

# REST API routers
app.include_router(portfolio.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(prices.router, prefix="/api")

# Chat router (built by LLM Engineer — graceful fallback during parallel development)
try:
    from app.routers import chat  # noqa: PLC0415

    app.include_router(chat.router, prefix="/api")
except ImportError:
    pass

# Serve Next.js static export (SPA fallback via html=True)
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
