from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Config
from app.main import app
from app.models import CountryConfig, RadioInfo


def _country_config(**kwargs) -> CountryConfig:
    return CountryConfig(**kwargs)


@pytest.fixture
def config():
    return Config(
        timezone="America/Santiago",
        notification_window_minutes=30,
        default_match_duration_minutes=120,
        teams=["Colo-Colo"],
        team_mapping={"Colo-Colo": ["Colo-Colo"]},
        radios={"Colo-Colo": RadioInfo(label="Test Radio", url="https://example.com")},
    )


@pytest.fixture
def config_countries():
    return Config(
        timezone="America/Santiago",
        notification_window_minutes=30,
        default_match_duration_minutes=120,
        countries={
            "Chile": _country_config(
                teams=["Colo-Colo"],
                team_mapping={"Colo-Colo": ["Colo-Colo"]},
                radios={"Colo-Colo": RadioInfo(label="Test Radio", url="https://example.com")},
                default_radio=RadioInfo(label="Radio Nacional", url="https://example.com/nacional"),
            ),
        },
    )


@pytest.fixture
def client(config, monkeypatch):
    monkeypatch.setattr(main_module, "load_config", lambda: config)
    with TestClient(app) as c:
        app.state.config = config
        app.state.football_client = MagicMock()
        app.state.football_client.get_today_matches.return_value = []
        yield c


@pytest.fixture
def client_countries(config_countries, monkeypatch):
    monkeypatch.setattr(main_module, "load_config", lambda: config_countries)
    with TestClient(app) as c:
        app.state.config = config_countries
        app.state.football_client = MagicMock()
        app.state.football_client.get_today_matches.return_value = []
        yield c


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestEventsToday:
    def test_empty_when_no_client(self, client):
        app.state.football_client = None
        resp = client.get("/events/today")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_events(self, client):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": f"{today}T19:30:00Z",
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Other Team"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]
        resp = client.get("/events/today")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["type"] == "sports_event"
        assert data[0]["team"] == "Colo-Colo"

    def test_no_config_returns_500(self, client):
        app.state.config = None
        resp = client.get("/events/today")
        assert resp.status_code == 500


class TestBlocksToday:
    def test_empty_when_no_client(self, client):
        app.state.football_client = None
        resp = client.get("/radioflow/blocks/today")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_blocks(self, client):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": f"{today}T19:30:00Z",
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Other Team"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]
        resp = client.get("/radioflow/blocks/today")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        block = data[0]
        assert block["provider"] == "sports-notifier"
        assert block["kind"] == "external_audio_recommendation"
        assert block["action"]["type"] == "open_stream"
        assert "sport" in block["metadata"]

    def test_no_config_returns_500(self, client):
        app.state.config = None
        resp = client.get("/radioflow/blocks/today")
        assert resp.status_code == 500


class TestEventsTodayWithCountry:
    def test_filters_by_country(self, client_countries):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": f"{today}T19:30:00Z",
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Other Team"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]
        resp = client_countries.get("/events/today?country=Chile")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["team"] == "Colo-Colo"

    def test_international_match_with_default_radio(self, client_countries):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 456,
                "utcDate": f"{today}T19:30:00Z",
                "status": "SCHEDULED",
                "homeTeam": {"id": 10, "name": "Mexico"},
                "awayTeam": {"id": 11, "name": "South Africa"},
                "competition": {"id": 2014, "name": "Friendly"},
            }
        ]
        resp = client_countries.get("/events/today?country=Chile")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["team"] == "Internacional"
        assert data[0]["radio"]["label"] == "Radio Nacional"


class TestBlocksTodayWithCountry:
    def test_blocks_with_country(self, client_countries):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": f"{today}T19:30:00Z",
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Other Team"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]
        resp = client_countries.get("/radioflow/blocks/today?country=Chile")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert data[0]["metadata"]["team"] == "Colo-Colo"
