import unittest
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None)))
sys.modules.setdefault("yfinance", SimpleNamespace(Ticker=None))
FETCH_PRICES_IMPORT_ERROR = None
try:
    from core.fetch_prices import get_price_changes
except ModuleNotFoundError as exc:
    FETCH_PRICES_IMPORT_ERROR = exc
    get_price_changes = None


class _FakeSeries:
    def __init__(self, values):
        self._values = values

    @property
    def iloc(self):
        return self

    def __getitem__(self, idx):
        return self._values[idx]


class _FakeIndex:
    def __init__(self, dates):
        self._dates = dates

    def __getitem__(self, idx):
        return self._dates[idx]

    def __ge__(self, other):
        if isinstance(other, str):
            other_dt = datetime.fromisoformat(other)
        else:
            other_dt = other
        return [d >= other_dt for d in self._dates]


class _FakeData:
    def __init__(self, dates, closes):
        self._dates = dates
        self._closes = closes
        self.index = _FakeIndex(dates)

    def dropna(self, subset=None):
        return self

    def __len__(self):
        return len(self._closes)

    def __getitem__(self, key):
        if key == "Close":
            return _FakeSeries(self._closes)
        if isinstance(key, list):  # bool mask
            dates = [d for d, keep in zip(self._dates, key) if keep]
            closes = [c for c, keep in zip(self._closes, key) if keep]
            return _FakeData(dates, closes)
        raise KeyError(key)


class _TickerMock:
    def __init__(self, recent_df, hist_df):
        self._recent_df = recent_df
        self._hist_df = hist_df

    def history(self, period=None, start=None, interval=None):
        if start is not None:
            return self._hist_df
        return self._recent_df


@unittest.skipIf(FETCH_PRICES_IMPORT_ERROR is not None, f"optional dependency missing: {FETCH_PRICES_IMPORT_ERROR}")
class TestFetchPrices(unittest.TestCase):
    @patch("core.fetch_prices.yf.Ticker")
    def test_since_watchlist_is_calculated_from_added_at_when_close_missing(self, ticker_cls):
        recent = _FakeData(
            [datetime(2026, 3, 20), datetime(2026, 3, 21)],
            [110.0, 121.0],
        )
        hist = _FakeData(
            [datetime(2026, 1, 2), datetime(2026, 1, 3)],
            [100.0, 101.0],
        )

        ticker_cls.return_value = _TickerMock(recent, hist)
        items = [
            {
                "ticker": "V",
                "name": "Visa Inc.",
                "watchlist_added_at": "2026-01-01T00:00:00",
            }
        ]

        result, _ = get_price_changes(items)
        self.assertEqual(1, len(result))
        # (121 - 100) / 100 * 100 = 21%
        self.assertEqual(21.0, result[0].since_watchlist_percent)


if __name__ == "__main__":
    unittest.main()
