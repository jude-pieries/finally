"""FinAlly Market Data Simulator Demo.

Run with:  uv run market_data_demo.py

Displays a live-updating terminal dashboard of simulated stock prices
using the GBM simulator and Rich library. Demonstrates the full PriceCache
API including get_history(), daily_change_percent, and push-on-change versioning.
"""

from __future__ import annotations

import asyncio
import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource

# Sparkline characters, low to high
SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Ordered ticker list matching the default watchlist
TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

DURATION = 60       # seconds to run before auto-exit
SPARK_POINTS = 40   # number of history points to show in sparkline


def sparkline(values: list[float]) -> str:
    """Render a sequence of floats as a unicode sparkline."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    spread = hi - lo
    if spread == 0:
        return SPARK_CHARS[3] * len(values)
    n = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[int((v - lo) / spread * n)] for v in values)


def fmt_price(price: float) -> str:
    return f"{price:,.2f}" if price >= 1000 else f"{price:.2f}"


def build_table(cache: PriceCache) -> Table:
    """Build the live prices table using PriceCache directly."""
    table = Table(
        expand=True,
        border_style="bright_black",
        header_style="bold bright_white",
        pad_edge=True,
        padding=(0, 1),
    )
    table.add_column("Ticker",   style="bold bright_white", width=7)
    table.add_column("Price",    justify="right", width=10)
    table.add_column("Chg",      justify="right", width=8)
    table.add_column("Tick %",   justify="right", width=8)
    table.add_column("Daily %",  justify="right", width=8)
    table.add_column("",         width=2)   # arrow
    table.add_column("Sparkline (last 40 pts)", width=44, no_wrap=True)

    for ticker in TICKERS:
        update = cache.get(ticker)
        if update is None:
            table.add_row(ticker, "---", "---", "---", "---", "", "")
            continue

        if update.direction == "up":
            color, arrow = "green",        "[bold green]▲[/]"
        elif update.direction == "down":
            color, arrow = "red",          "[bold red]▼[/]"
        else:
            color, arrow = "bright_black", "[bright_black]─[/]"

        daily_color = "green" if update.daily_change_percent > 0 else (
                      "red"   if update.daily_change_percent < 0 else "bright_black")

        # Sparkline from PriceCache.get_history()
        hist = cache.get_history(ticker)
        prices = [p["price"] for p in hist[-SPARK_POINTS:]]
        spark = f"[bright_cyan]{sparkline(prices)}[/]" if len(prices) > 1 else ""

        table.add_row(
            ticker,
            f"[{color}]${fmt_price(update.price)}[/]",
            f"[{color}]{update.change:+.2f}[/]",
            f"[{color}]{update.change_percent:+.2f}%[/]",
            f"[{daily_color}]{update.daily_change_percent:+.2f}%[/]",
            arrow,
            spark,
        )

    return table


def build_event_log(events: list[str]) -> Panel:
    text = Text()
    for evt in events:
        text.append(evt)
        text.append("\n")
    if not events:
        text.append("Watching for notable moves (>1% tick change)…", style="bright_black italic")
    return Panel(
        text,
        title="[bold bright_yellow]Recent Events[/]",
        border_style="bright_black",
        height=8,
    )


def build_dashboard(
    cache: PriceCache,
    events: list[str],
    start_time: float,
) -> Layout:
    elapsed   = time.time() - start_time
    remaining = max(0.0, DURATION - elapsed)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10),
    )

    header_text = Text.assemble(
        ("  FinAlly ", "bold bright_yellow"),
        ("Market Data Demo", "bold bright_white"),
        ("  |  ", "bright_black"),
        (f"{elapsed:5.1f}s elapsed", "bright_cyan"),
        ("  |  ", "bright_black"),
        (f"{remaining:4.1f}s remaining", "bright_cyan"),
        ("  |  ", "bright_black"),
        (f"{len(cache)} tickers  v{cache.version}", "bright_white"),
        ("  |  ", "bright_black"),
        ("Ctrl+C to exit", "bright_black italic"),
    )
    layout["header"].update(Panel(header_text, border_style="bright_yellow"))
    layout["body"].update(
        Panel(build_table(cache), title="[bold bright_white]Live Prices[/]", border_style="bright_black")
    )
    layout["footer"].update(build_event_log(events))
    return layout


def print_summary(cache: PriceCache) -> None:
    console = Console()
    console.print()
    console.print("[bold bright_yellow]  FinAlly[/] [bold]Session Summary[/]")
    console.print()

    table = Table(border_style="bright_black", header_style="bold bright_white", expand=False)
    table.add_column("Ticker",         style="bold bright_white", width=8)
    table.add_column("Open Price",     justify="right", width=12)
    table.add_column("Final Price",    justify="right", width=12)
    table.add_column("Daily Change",   justify="right", width=13)
    table.add_column("History Points", justify="right", width=14)

    for ticker in TICKERS:
        update = cache.get(ticker)
        if update is None:
            continue
        color = "green" if update.daily_change_percent > 0 else (
                "red"   if update.daily_change_percent < 0 else "bright_black")
        n_history = len(cache.get_history(ticker))
        table.add_row(
            ticker,
            f"${fmt_price(update.open_price)}",
            f"[{color}]${fmt_price(update.price)}[/]",
            f"[{color}]{update.daily_change_percent:+.2f}%[/]",
            str(n_history),
        )

    console.print(table)
    console.print()


async def run() -> None:
    cache  = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.5)
    events: list[str] = []

    await source.start(TICKERS)
    start_time = time.time()

    try:
        with Live(
            build_dashboard(cache, events, start_time),
            refresh_per_second=4,
            screen=True,
        ) as live:
            last_version = cache.version

            while time.time() - start_time < DURATION:
                await asyncio.sleep(0.25)

                if cache.version == last_version:
                    continue
                last_version = cache.version

                # Detect notable tick events
                for ticker in TICKERS:
                    update = cache.get(ticker)
                    if update and abs(update.change_percent) > 1.0:
                        direction = "▲" if update.direction == "up" else "▼"
                        color     = "green" if update.direction == "up" else "red"
                        ts        = time.strftime("%H:%M:%S")
                        events.insert(0,
                            f"[bright_black]{ts}[/]  "
                            f"[bold {color}]{direction} {ticker}[/]  "
                            f"[{color}]{update.change_percent:+.2f}%[/]  "
                            f"${fmt_price(update.price)}"
                        )
                        if len(events) > 12:
                            events.pop()

                live.update(build_dashboard(cache, events, start_time))

    except KeyboardInterrupt:
        pass
    finally:
        await source.stop()

    print_summary(cache)


if __name__ == "__main__":
    asyncio.run(run())
