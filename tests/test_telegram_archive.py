import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("loguru", SimpleNamespace(logger=SimpleNamespace(error=lambda *a, **k: None)))
import utils.telegram_archive as ta


class TestTelegramArchive(unittest.TestCase):
    def test_archive_outgoing_message_writes_compact_gzip_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "telegram"
            with patch.object(ta, "ARCHIVE_ROOT", root):
                ta.archive_outgoing_message(
                    chat_id="12345",
                    message_id=777,
                    text="Test Nachricht",
                    parse_mode="HTML",
                    source="unit-test",
                )

            files = list(root.rglob("*.jsonl.gz"))
            self.assertEqual(1, len(files))

            with gzip.open(files[0], "rt", encoding="utf-8") as f:
                line = f.readline()
            payload = json.loads(line)
            self.assertEqual("12345", payload["chat_id"])
            self.assertEqual(777, payload["message_id"])
            self.assertEqual("Test Nachricht", payload["text"])
            self.assertEqual("HTML", payload["parse_mode"])
            self.assertEqual("unit-test", payload["source"])
            self.assertEqual(len("Test Nachricht"), payload["len"])
            self.assertTrue(payload["sha256"])


if __name__ == "__main__":
    unittest.main()
