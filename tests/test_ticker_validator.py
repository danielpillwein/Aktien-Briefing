import unittest
from unittest.mock import MagicMock, patch

TICKER_VALIDATOR_IMPORT_ERROR = None
try:
    from utils.ticker_validator import (
        normalize_ticker,
        validate_ticker_exists_yfinance,
        validate_ticker_syntax,
    )
except ModuleNotFoundError as exc:
    TICKER_VALIDATOR_IMPORT_ERROR = exc


@unittest.skipIf(TICKER_VALIDATOR_IMPORT_ERROR is not None, f"optional dependency missing: {TICKER_VALIDATOR_IMPORT_ERROR}")
class TestTickerValidator(unittest.TestCase):
    def test_normalize_ticker(self):
        self.assertEqual(normalize_ticker(" msft "), "MSFT")

    def test_validate_ticker_syntax(self):
        ok, _ = validate_ticker_syntax("ENR.DE")
        self.assertTrue(ok)

        ok, _ = validate_ticker_syntax("BAD TICKER")
        self.assertFalse(ok)

    @patch("utils.ticker_validator.yf.Ticker")
    def test_validate_ticker_exists_success(self, ticker_cls):
        ticker = MagicMock()
        history_df = MagicMock()
        history_df.empty = False
        ticker.history.return_value = history_df
        ticker_cls.return_value = ticker

        ok, _ = validate_ticker_exists_yfinance("MSFT")
        self.assertTrue(ok)

    @patch("utils.ticker_validator.yf.Ticker")
    def test_validate_ticker_exists_empty(self, ticker_cls):
        ticker = MagicMock()
        history_df = MagicMock()
        history_df.empty = True
        ticker.history.return_value = history_df
        ticker_cls.return_value = ticker

        ok, _ = validate_ticker_exists_yfinance("XXXX")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
