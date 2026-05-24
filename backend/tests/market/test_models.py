"""Tests for PriceUpdate dataclass."""

import pytest

from app.market.models import PriceUpdate


def make_update(**kwargs) -> PriceUpdate:
    defaults = dict(ticker="AAPL", price=190.50, previous_price=190.00, open_price=190.00, timestamp=1234567890.0)
    defaults.update(kwargs)
    return PriceUpdate(**defaults)


class TestPriceUpdate:
    def test_price_update_creation(self):
        update = make_update()
        assert update.ticker == "AAPL"
        assert update.price == 190.50
        assert update.previous_price == 190.00
        assert update.open_price == 190.00
        assert update.timestamp == 1234567890.0

    def test_change_calculation(self):
        assert make_update(price=190.50, previous_price=190.00).change == 0.50

    def test_change_negative(self):
        assert make_update(price=189.50, previous_price=190.00).change == -0.50

    def test_change_percent_up(self):
        assert make_update(price=190.00, previous_price=100.00).change_percent == 90.0

    def test_change_percent_down(self):
        assert make_update(price=100.00, previous_price=200.00).change_percent == -50.0

    def test_change_percent_zero_previous(self):
        assert make_update(price=100.00, previous_price=0.00).change_percent == 0.0

    def test_daily_change_percent_up(self):
        update = make_update(price=200.00, open_price=100.00)
        assert update.daily_change_percent == 100.0

    def test_daily_change_percent_down(self):
        update = make_update(price=90.00, open_price=100.00)
        assert update.daily_change_percent == -10.0

    def test_daily_change_percent_zero_open(self):
        update = make_update(price=100.00, open_price=0.00)
        assert update.daily_change_percent == 0.0

    def test_direction_up(self):
        assert make_update(price=191.00, previous_price=190.00).direction == "up"

    def test_direction_down(self):
        assert make_update(price=189.00, previous_price=190.00).direction == "down"

    def test_direction_flat(self):
        assert make_update(price=190.00, previous_price=190.00).direction == "flat"

    def test_to_sse_dict_has_exactly_five_fields(self):
        result = make_update().to_sse_dict()
        assert set(result.keys()) == {"ticker", "price", "previous_price", "open_price", "timestamp"}

    def test_to_sse_dict_values(self):
        update = make_update(price=191.00, previous_price=190.00, open_price=188.00, timestamp=999.0)
        result = update.to_sse_dict()
        assert result["ticker"] == "AAPL"
        assert result["price"] == 191.00
        assert result["previous_price"] == 190.00
        assert result["open_price"] == 188.00
        assert result["timestamp"] == 999.0

    def test_to_dict_full_fields(self):
        update = make_update(price=190.50, previous_price=190.00, open_price=185.00)
        result = update.to_dict()
        assert result["ticker"] == "AAPL"
        assert result["price"] == 190.50
        assert result["previous_price"] == 190.00
        assert result["open_price"] == 185.00
        assert result["change"] == 0.50
        assert "change_percent" in result
        assert "daily_change_percent" in result
        assert result["direction"] == "up"

    def test_immutability(self):
        update = make_update()
        with pytest.raises(AttributeError):
            update.price = 200.00
