"""Tests for PriceCache."""

from app.market.cache import PriceCache


class TestPriceCache:
    def test_update_and_get(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.ticker == "AAPL"
        assert update.price == 190.50
        assert cache.get("AAPL") == update

    def test_first_update_is_flat(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.direction == "flat"
        assert update.previous_price == 190.50

    def test_direction_up(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 191.00)
        assert update.direction == "up"
        assert update.change == 1.00

    def test_direction_down(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 189.00)
        assert update.direction == "down"
        assert update.change == -1.00

    def test_open_price_set_on_first_update(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("AAPL", 195.00)
        cache.update("AAPL", 185.00)
        # open_price should remain the first price across all updates
        assert cache.get("AAPL").open_price == 190.00

    def test_open_price_frozen_at_seed(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 200.00)
        assert update.open_price == 190.00

    def test_remove(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get("AAPL") is None

    def test_remove_clears_history(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get_history("AAPL") == []

    def test_remove_clears_ticker_version(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert "AAPL" not in cache.get_ticker_versions()

    def test_remove_increments_global_version(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        v = cache.version
        cache.remove("AAPL")
        assert cache.version == v + 1

    def test_remove_nonexistent(self):
        cache = PriceCache()
        cache.remove("AAPL")  # Should not raise

    def test_get_all(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        all_prices = cache.get_all()
        assert set(all_prices.keys()) == {"AAPL", "GOOGL"}

    def test_version_increments_on_update(self):
        cache = PriceCache()
        v0 = cache.version
        cache.update("AAPL", 190.00)
        assert cache.version == v0 + 1
        cache.update("AAPL", 191.00)
        assert cache.version == v0 + 2

    def test_per_ticker_version_increments(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        v1 = cache.get_ticker_versions()["AAPL"]
        cache.update("AAPL", 191.00)
        v2 = cache.get_ticker_versions()["AAPL"]
        assert v2 == v1 + 1

    def test_per_ticker_versions_are_independent(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("TSLA", 250.00)
        cache.update("AAPL", 191.00)
        versions = cache.get_ticker_versions()
        assert versions["AAPL"] == 2
        assert versions["TSLA"] == 1

    def test_history_accumulates(self):
        cache = PriceCache()
        for i in range(5):
            cache.update("AAPL", 190.0 + i)
        history = cache.get_history("AAPL")
        assert len(history) == 5
        assert history[0]["price"] == 190.0
        assert history[-1]["price"] == 194.0

    def test_history_capped_at_200(self):
        cache = PriceCache()
        for i in range(250):
            cache.update("AAPL", float(i))
        assert len(cache.get_history("AAPL")) == 200

    def test_history_oldest_first(self):
        cache = PriceCache()
        prices = [100.0, 101.0, 102.0]
        for p in prices:
            cache.update("AAPL", p)
        history = cache.get_history("AAPL")
        assert [h["price"] for h in history] == prices

    def test_history_empty_for_unknown_ticker(self):
        cache = PriceCache()
        assert cache.get_history("NOPE") == []

    def test_history_contains_timestamp(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00, timestamp=1234567890.0)
        history = cache.get_history("AAPL")
        assert history[0]["timestamp"] == 1234567890.0

    def test_get_price_convenience(self):
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("NOPE") is None

    def test_len(self):
        cache = PriceCache()
        assert len(cache) == 0
        cache.update("AAPL", 190.00)
        assert len(cache) == 1
        cache.update("GOOGL", 175.00)
        assert len(cache) == 2

    def test_contains(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert "AAPL" in cache
        assert "GOOGL" not in cache

    def test_custom_timestamp(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.50, timestamp=1234567890.0)
        assert update.timestamp == 1234567890.0

    def test_price_rounding(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.12345)
        assert update.price == 190.12
