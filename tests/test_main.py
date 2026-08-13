from datetime import datetime
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Config
from app.hosted_configuration import HostedConfigurationStore
from app.main import app
from app.models import CountryConfig, RadioInfo
from tests.conftest import today_at_utc


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
def client(config, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "load_config", lambda: config)
    with TestClient(app) as c:
        app.state.config = config
        app.state.football_client = MagicMock()
        app.state.football_client.get_today_matches.return_value = []
        app.state.api_football_client = MagicMock()
        app.state.api_football_client.get_leagues.return_value = []
        app.state.api_football_client.get_teams.return_value = []
        app.state.api_football_client.get_fixtures.return_value = []
        app.state.configuration_store = HostedConfigurationStore(tmp_path / "hosted.db", "test-secret-" * 4)
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
        assert resp.json() == {"status": "ok", "version": "0.2.0"}

    def test_health_is_degraded_without_provider_credentials(self, client):
        app.state.api_football_client = None

        resp = client.get("/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "degraded", "version": "0.2.0"}


class TestAddonManifest:
    def test_exposes_radioflow_manifest_v1(self, client):
        resp = client.get("/manifest.json")

        assert resp.status_code == 200
        assert resp.json() == {
            "manifestVersion": 1,
            "id": "app.radioflow.sports",
            "name": "Sports Notifications",
            "description": "Scheduled sports events from the hosted RadioFlow service.",
            "version": "0.2.0",
            "author": "RadioFlow",
            "capabilities": ["notifications", "suggest_blocks"],
            "events": ["suggest_block"],
            "configuration": {
                "type": "web",
                "start": "/configuration/start",
                "exchange": "/configuration/exchange",
            },
            "endpoints": {"health": "/health", "events": "/addon/events"},
        }


class TestAddonEvents:
    def test_requires_an_opaque_configuration_header(self, client):
        resp = client.get("/addon/events")
        assert resp.status_code == 401

    def test_configuration_handshake_filters_and_emits_generic_suggestions(self, client):
        state = "s" * 43
        started = client.post("/configuration/start", json={
            "callbackUrl": "http://testserver/api/addons/configuration/callback",
            "state": state,
            "mode": "install",
        })
        assert started.status_code == 200
        session_id = started.json()["configureUrl"].rsplit("/", 1)[-1]
        page = client.get(f"/configure/{session_id}")
        assert page.status_code == 200
        assert "Instalar en RadioFlow" in page.text
        completed = client.post(f"/configure/{session_id}/complete", json={
            "competition": {"id": 265, "name": "Primera División", "season": 2026},
            "teams": [{"id": 2285, "name": "Colo-Colo"}],
            "events": ["match.scheduled"],
        })
        callback = urlparse(completed.json()["callbackUrl"])
        callback_query = parse_qs(callback.query)
        assert callback_query["state"] == [state]
        exchanged = client.post("/configuration/exchange", json={"code": callback_query["code"][0]})
        assert exchanged.status_code == 200
        config_id = exchanged.json()["configId"]
        assert "Primera División" in exchanged.json()["summary"]["lines"][0]
        assert client.post("/configuration/exchange", json={"code": callback_query["code"][0]}).status_code == 400

        app.state.api_football_client.get_fixtures.return_value = [{
            "fixture": {"id": 123, "date": "2026-08-20T19:30:00-04:00", "status": {"short": "NS"}},
            "league": {"id": 265, "name": "Primera División"},
            "teams": {
                "home": {"id": 2285, "name": "Colo-Colo"},
                "away": {"id": 2290, "name": "Universidad de Chile"},
            },
        }]
        resp = client.get("/addon/events", headers={"X-RadioFlow-Config-Id": config_id})

        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["type"] == "suggest_block"
        assert events[0]["source"] == "app.radioflow.sports"
        assert events[0]["data"]["externalContentId"] == "api-football:123"
        assert events[0]["data"]["metadata"]["eventType"] == "match.scheduled"
        assert events[0]["data"]["metadata"]["source"] == "api-football.com"

    def test_catalog_endpoints_use_api_football_without_exposing_credentials(self, client):
        started = client.post("/configuration/start", json={
            "callbackUrl": "http://testserver/api/addons/configuration/callback",
            "state": "x" * 43,
            "mode": "install",
        })
        session_id = started.json()["configureUrl"].rsplit("/", 1)[-1]
        app.state.api_football_client.get_leagues.return_value = [{
            "league": {"id": 265, "name": "Primera División"},
            "seasons": [{"year": 2026, "current": True}],
        }]
        app.state.api_football_client.get_teams.return_value = [{
            "team": {"id": 2285, "name": "Colo-Colo", "logo": "https://media.example/colo.png"},
        }]
        leagues = client.get(f"/configure/api/leagues?session={session_id}")
        teams = client.get(f"/configure/api/teams?session={session_id}&league=265&season=2026")
        assert leagues.json() == [{"id": 265, "name": "Primera División", "season": 2026}]
        assert teams.json()[0]["name"] == "Colo-Colo"


class TestEventsToday:
    def test_empty_when_no_client(self, client):
        app.state.football_client = None
        resp = client.get("/events/today")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_events(self, client):
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": today_at_utc(),
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
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": today_at_utc(),
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
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": today_at_utc(),
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
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 456,
                "utcDate": today_at_utc(),
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
        app.state = client_countries.app.state
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": today_at_utc(),
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


class TestSuggestionsToday:
    def test_returns_radioflow_v0_suggestions(self, client):
        today = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d")
        app.state.football_client.get_today_matches.return_value = [
            {
                "id": 123,
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Other Team"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]

        resp = client.get("/radioflow/suggestions/today?source_key=sports-test")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        suggestion = data[0]
        assert suggestion["sourceKey"] == "sports-test"
        assert suggestion["externalContentId"] == "sports-match-123"
        assert suggestion["suggestedDate"] == today
        assert suggestion["suggestedStartTime"]
        assert suggestion["suggestedEndTime"]
        assert suggestion["contentKind"] == "metadata_only"
        assert suggestion["contentMode"] == "reference_only"
        assert suggestion["renderMode"] == "display_card"
        assert suggestion["conflictPolicy"] == "reject"

    def test_source_key_is_required(self, client):
        resp = client.get("/radioflow/suggestions/today")

        assert resp.status_code == 422
