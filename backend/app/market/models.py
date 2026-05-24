"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    open_price: float                                          # Reference/open price; used for daily change %
    timestamp: float = field(default_factory=time.time)       # Unix seconds

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update (tick-to-tick)."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def daily_change_percent(self) -> float:
        """Percentage change from the open/reference price."""
        if self.open_price == 0:
            return 0.0
        return round((self.price - self.open_price) / self.open_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat' relative to the previous tick."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_sse_dict(self) -> dict:
        """Serialize for SSE transmission — exactly the five fields in the SSE contract.

        Direction and change % are derived client-side.
        """
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
        }

    def to_dict(self) -> dict:
        """Full serialization including all computed fields.

        Used by portfolio and trade API responses.
        """
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "open_price": self.open_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "daily_change_percent": self.daily_change_percent,
            "direction": self.direction,
        }
