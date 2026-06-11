import json
import os
import tempfile
from unittest.mock import patch

from app.storage import NotificationStore


class TestNotificationStore:
    def test_new_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            store = NotificationStore(path)
            assert store.is_sent("match-1") is False

    def test_mark_and_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            store = NotificationStore(path)
            store.mark_sent("match-1")
            assert store.is_sent("match-1") is True
            assert store.is_sent("match-2") is False

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            store = NotificationStore(path)
            store.mark_sent("match-1")
            store.mark_sent("match-2")

            store2 = NotificationStore(path)
            assert store2.is_sent("match-1") is True
            assert store2.is_sent("match-2") is True
            assert store2.is_sent("match-3") is False

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json")
            store = NotificationStore(path)
            assert store.is_sent("anything") is False
            store.mark_sent("new-id")
            assert store.is_sent("new-id") is True

    def test_duplicate_mark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            store = NotificationStore(path)
            store.mark_sent("match-1")
            store.mark_sent("match-1")
            store.mark_sent("match-1")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 1

    def test_unexpected_format_resets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"key": "value"}, f)
            store = NotificationStore(path)
            assert store.is_sent("anything") is False

    def test_save_oserror_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "notifications.json")
            store = NotificationStore(path)
            with patch("builtins.open") as mock_open:
                mock_open.side_effect = OSError("Permission denied")
                store.mark_sent("match-1")
