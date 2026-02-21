import importlib
import os
import unittest
from unittest.mock import MagicMock


class TestTelegramCommandHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"
        os.environ["TELEGRAM_CHAT_ID"] = "123456"
        global telegram_commands
        try:
            telegram_commands = importlib.import_module("core.telegram_commands")
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"optional dependency missing: {exc}")

    def test_parse_add_args(self):
        ticker, name = telegram_commands.parse_add_args(["MSFT", "Microsoft", "Corp"])
        self.assertEqual(ticker, "MSFT")
        self.assertEqual(name, "Microsoft Corp")

    def test_parse_add_args_invalid(self):
        with self.assertRaises(ValueError):
            telegram_commands.parse_add_args(["MSFT"])

    def test_parse_remove_args(self):
        ticker = telegram_commands.parse_remove_args(["nvda"])
        self.assertEqual(ticker, "NVDA")

    def test_parse_remove_args_invalid(self):
        with self.assertRaises(ValueError):
            telegram_commands.parse_remove_args(["NVDA", "EXTRA"])

    def test_is_authorized(self):
        update = MagicMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = 123456
        self.assertTrue(telegram_commands._is_authorized(update))

        update.effective_chat.id = 42
        self.assertFalse(telegram_commands._is_authorized(update))


if __name__ == "__main__":
    unittest.main()
