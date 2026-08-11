from unittest.mock import MagicMock

from app.match_service import _match_team, get_relevant_matches
from tests.conftest import today_at_utc


class TestMatchTeam:
    def test_exact_match(self, sample_config):
        result = _match_team("Colo-Colo", sample_config.team_mapping)
        assert result == "Colo-Colo"

    def test_substring_match(self, sample_config):
        result = _match_team("CD Colo-Colo", sample_config.team_mapping)
        assert result == "Colo-Colo"

    def test_case_insensitive(self, sample_config):
        result = _match_team("colo-colo", sample_config.team_mapping)
        assert result == "Colo-Colo"

    def test_no_match(self, sample_config):
        result = _match_team("Real Madrid", sample_config.team_mapping)
        assert result is None


class TestGetRelevantMatches:
    def test_filters_correctly(self, sample_config, sample_match):
        client = MagicMock()
        client.get_today_matches.return_value = [sample_match]

        events = get_relevant_matches(sample_config, client)

        assert len(events) >= 1
        colo_events = [e for e in events if e.team == "Colo-Colo"]
        assert len(colo_events) > 0
        assert colo_events[0].radio is not None
        assert colo_events[0].radio.label == "Cooperativa 93.3 FM"

    def test_no_matches(self, sample_config):
        client = MagicMock()
        client.get_today_matches.return_value = []

        events = get_relevant_matches(sample_config, client)
        assert events == []

    def test_irrelevant_teams_skipped(self, sample_config):
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "id": 999,
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 10, "name": "Real Madrid"},
                "awayTeam": {"id": 11, "name": "Barcelona"},
                "competition": {"id": 2014, "name": "La Liga"},
            }
        ]

        events = get_relevant_matches(sample_config, client)
        assert events == []

    def test_team_without_radio(self, sample_config):
        sample_config.radios = {}
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "id": 111,
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Universidad Católica"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]

        events = get_relevant_matches(sample_config, client)
        assert len(events) > 0
        assert events[0].radio is None

    def test_invalid_date_skipped(self, sample_config):
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "id": 222,
                "utcDate": "invalid-date",
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Universidad Católica"},
                "competition": {"id": 2024, "name": "Primera División"},
            }
        ]

        events = get_relevant_matches(sample_config, client)
        assert events == []

    def test_missing_id_skipped(self, sample_config):
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 1, "name": "Colo-Colo"},
                "awayTeam": {"id": 2, "name": "Universidad Católica"},
            }
        ]

        events = get_relevant_matches(sample_config, client)
        assert events == []


class TestGetRelevantMatchesWithCountry:
    def test_filters_by_country(self, sample_config_countries, sample_match):
        client = MagicMock()
        client.get_today_matches.return_value = [sample_match]

        events = get_relevant_matches(sample_config_countries, client, country="Chile")

        assert len(events) >= 1
        assert all(e.team == "Colo-Colo" for e in events)
        assert events[0].radio.label == "Cooperativa 93.3 FM"

    def test_international_match_uses_default_radio(self, sample_config_countries):
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "id": 999,
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 10, "name": "Mexico"},
                "awayTeam": {"id": 11, "name": "South Africa"},
                "competition": {"id": 2014, "name": "Friendly"},
            }
        ]

        events = get_relevant_matches(sample_config_countries, client, country="Chile")

        assert len(events) == 1
        assert events[0].team == "Internacional"
        assert events[0].radio.label == "Radio Cooperativa"

    def test_international_match_not_shown_without_country(self, sample_config_countries):
        client = MagicMock()
        client.get_today_matches.return_value = [
            {
                "id": 999,
                "utcDate": today_at_utc(),
                "status": "SCHEDULED",
                "homeTeam": {"id": 10, "name": "Mexico"},
                "awayTeam": {"id": 11, "name": "South Africa"},
                "competition": {"id": 2014, "name": "Friendly"},
            }
        ]

        events = get_relevant_matches(sample_config_countries, client)

        assert events == []
