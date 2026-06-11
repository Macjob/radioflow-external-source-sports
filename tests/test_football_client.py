from unittest.mock import MagicMock, patch

import pytest
import requests

from app.football_client import BASE_URL, FootballDataClient


@pytest.fixture
def client():
    return FootballDataClient(api_key="test-key-123")


class TestFootballDataClient:
    def test_init_sets_api_key(self):
        c = FootballDataClient(api_key="abc")
        assert c.api_key == "abc"
        assert c.timeout == 10

    def test_get_today_matches_success(self, client, sample_matches):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_matches
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp) as mock_get:
            result = client.get_today_matches()

        mock_get.assert_called_once_with(f"{BASE_URL}/matches", timeout=10)
        assert len(result) == 2
        assert result[0]["id"] == 123456

    def test_get_today_matches_connection_error(self, client):
        with patch("requests.Session.get", side_effect=requests.ConnectionError("no route to host")):
            result = client.get_today_matches()
        assert result == []

    def test_get_today_matches_timeout(self, client):
        with patch("requests.Session.get", side_effect=requests.Timeout("timed out")):
            result = client.get_today_matches()
        assert result == []

    def test_get_today_matches_http_403(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden", response=mock_resp)

        with patch("requests.Session.get", return_value=mock_resp):
            result = client.get_today_matches()
        assert result == []

    def test_get_today_matches_invalid_json(self, client):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.get", return_value=mock_resp):
            result = client.get_today_matches()
        assert result == []

    def test_session_reuse(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"matches": []}
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_resp
            mock_session_cls.return_value = mock_session

            client.get_today_matches()
            client.get_today_matches()

        assert mock_session_cls.call_count == 1
