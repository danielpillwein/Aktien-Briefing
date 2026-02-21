import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import utils.settings_repository as repo


class TestSettingsRepository(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmpdir.name) / "settings.yaml"
        self.backup_dir = Path(self.tmpdir.name) / "backups"
        base_settings = {
            "portfolio": [{"ticker": "MSFT", "name": "Microsoft"}],
            "watchlist": [{"ticker": "NVDA", "name": "Nvidia"}],
        }
        self.settings_path.write_text(
            yaml.safe_dump(base_settings, sort_keys=False),
            encoding="utf-8",
        )
        self.patch_settings = patch.object(repo, "SETTINGS_PATH", self.settings_path)
        self.patch_backups = patch.object(repo, "BACKUP_DIR", self.backup_dir)
        self.patch_settings.start()
        self.patch_backups.start()

    def tearDown(self):
        self.patch_backups.stop()
        self.patch_settings.stop()
        self.tmpdir.cleanup()

    def test_add_stock_persists_and_creates_backup(self):
        result = repo.add_stock("portfolio", "AAPL", "Apple")
        self.assertEqual(result["ticker"], "AAPL")

        settings = repo.load_settings_file()
        self.assertTrue(any(s["ticker"] == "AAPL" for s in settings["portfolio"]))
        backups = list(self.backup_dir.glob("settings-*.yaml"))
        self.assertTrue(backups)

    def test_add_duplicate_ticker_rejected(self):
        with self.assertRaises(ValueError):
            repo.add_stock("watchlist", "MSFT", "Microsoft Duplicate")

    def test_remove_stock_persists(self):
        result = repo.remove_stock("watchlist", "NVDA")
        self.assertEqual(result["ticker"], "NVDA")

        settings = repo.load_settings_file()
        self.assertFalse(any(s["ticker"] == "NVDA" for s in settings["watchlist"]))

    def test_remove_missing_ticker_raises(self):
        with self.assertRaises(KeyError):
            repo.remove_stock("watchlist", "TSM")


if __name__ == "__main__":
    unittest.main()
