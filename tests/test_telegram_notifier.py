from unittest.mock import MagicMock, patch

import pytest
import requests

from app.telegram_notifier import TelegramNotifier


@pytest.fixture
def notifier():
    return TelegramNotifier(bot_token="test:token", chat_id="12345")


class TestTelegramNotifier:
    def test_send_message_success(self, notifier):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = notifier.send_message("Hello!")

        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["chat_id"] == "12345"
        assert kwargs["json"]["text"] == "Hello!"

    def test_send_message_api_error(self, notifier):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "description": "Bot blocked"}
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            result = notifier.send_message("Hello!")
        assert result is False

    def test_send_message_http_error(self, notifier):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request", response=mock_resp)

        with patch("requests.post", return_value=mock_resp):
            result = notifier.send_message("Hello!")
        assert result is False

    def test_send_message_connection_error(self, notifier):
        with patch("requests.post", side_effect=requests.ConnectionError("failed")):
            result = notifier.send_message("Hello!")
        assert result is False

    def test_send_message_timeout(self, notifier):
        with patch("requests.post", side_effect=requests.Timeout("timed out")):
            result = notifier.send_message("Hello!")
        assert result is False

    def test_not_configured(self):
        n = TelegramNotifier(bot_token="", chat_id="")
        result = n.send_message("Hello!")
        assert result is False
