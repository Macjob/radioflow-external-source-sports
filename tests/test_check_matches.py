import os
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.check_matches import _build_message, main


class TestBuildMessage:
    def test_with_radio(self):
        event = MagicMock()
        event.team = "Colo-Colo"
        event.title = "Colo-Colo vs U. de Chile"
        event.starts_at.strftime.return_value = "19:30"
        event.radio.label = "Cooperativa 93.3 FM"
        event.radio.url = "https://www.cooperativa.cl"

        msg = _build_message(event)
        assert "Colo-Colo" in msg
        assert "19:30" in msg
        assert "Cooperativa 93.3 FM" in msg
        assert "https://www.cooperativa.cl" in msg

    def test_without_radio(self):
        event = MagicMock()
        event.team = "Colo-Colo"
        event.title = "Colo-Colo vs U. de Chile"
        event.starts_at.strftime.return_value = "19:30"
        event.radio = None

        msg = _build_message(event)
        assert "Colo-Colo" in msg
        assert "Escúchalo en:" not in msg


class TestMain:
    def _setup_patches(self, env_vars, event=None):
        stack = ExitStack()
        stack.enter_context(patch("app.check_matches.load_dotenv"))
        stack.enter_context(patch.dict(os.environ, env_vars, clear=True))

        mock_load_config = stack.enter_context(patch("app.check_matches.load_config"))
        mock_load_config.return_value = MagicMock(
            timezone="America/Santiago",
            notification_window_minutes=30,
        )

        stack.enter_context(patch("app.check_matches.FootballDataClient"))
        mock_notifier_cls = stack.enter_context(patch("app.check_matches.TelegramNotifier"))
        mock_store_cls = stack.enter_context(patch("app.check_matches.NotificationStore"))

        return_value = [event] if event else []
        stack.enter_context(patch("app.check_matches.get_relevant_matches", return_value=return_value))

        return stack, mock_notifier_cls, mock_store_cls

    def test_exits_when_no_api_key(self):
        with patch("app.check_matches.load_dotenv"):
            with patch.dict(os.environ, {}, clear=True):
                with pytest.raises(SystemExit):
                    main()

    def test_exits_when_empty_api_key(self):
        with patch("app.check_matches.load_dotenv"):
            with patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": ""}, clear=True):
                with pytest.raises(SystemExit):
                    main()

    def test_no_relevant_matches(self):
        stack, mock_notifier_cls, mock_store_cls = self._setup_patches(
            {"FOOTBALL_DATA_API_KEY": "test-key"},
        )
        with stack:
            main()

    def test_sends_notification_for_upcoming_match(self):
        now = datetime.now(timezone.utc)
        event = MagicMock()
        event.id = "match-123"
        event.starts_at = now + timedelta(minutes=15)
        event.team = "Colo-Colo"
        event.title = "Colo-Colo vs Other"
        event.radio = None

        stack, mock_notifier_cls, mock_store_cls = self._setup_patches(
            {
                "FOOTBALL_DATA_API_KEY": "test-key",
                "TELEGRAM_BOT_TOKEN": "bot:token",
                "TELEGRAM_CHAT_ID": "12345",
            },
            event=event,
        )
        with stack:
            mock_notifier = MagicMock()
            mock_notifier.send_message.return_value = True
            mock_notifier_cls.return_value = mock_notifier

            mock_store = MagicMock()
            mock_store.is_sent.return_value = False
            mock_store_cls.return_value = mock_store

            main()

            mock_notifier.send_message.assert_called_once()
            mock_store.mark_sent.assert_called_once_with(event.id)

    def test_skips_already_notified_match(self):
        now = datetime.now(timezone.utc)
        event = MagicMock()
        event.id = "match-123"
        event.starts_at = now + timedelta(minutes=15)
        event.team = "Colo-Colo"
        event.title = "Colo-Colo vs Other"
        event.radio = None

        stack, mock_notifier_cls, mock_store_cls = self._setup_patches(
            {
                "FOOTBALL_DATA_API_KEY": "test-key",
                "TELEGRAM_BOT_TOKEN": "bot:token",
                "TELEGRAM_CHAT_ID": "12345",
            },
            event=event,
        )
        with stack:
            mock_notifier = MagicMock()
            mock_notifier_cls.return_value = mock_notifier

            mock_store = MagicMock()
            mock_store.is_sent.return_value = True
            mock_store_cls.return_value = mock_store

            main()

            mock_notifier.send_message.assert_not_called()
