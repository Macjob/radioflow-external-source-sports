from datetime import datetime, timezone

from app.broadcast_catalog import (
    BroadcastCatalog,
    BroadcastStation,
    CompetitionBroadcastMapping,
)
from app.hosted_configuration import StoredConfiguration
from app.hosted_events import scheduled_matches_to_suggest_block_events
from app.sports_provider import ScheduledMatch, TeamRef


def _configuration() -> StoredConfiguration:
    return StoredConfiguration(
        config_hash="hash",
        competition={"id": "competition-a", "name": "Competition A", "season": "2026"},
        teams=[{"id": "competition-a:away", "name": "Away Team"}],
        events=["match.scheduled"],
        summary={},
    )


def _match() -> ScheduledMatch:
    return ScheduledMatch(
        id="match-123",
        competition_id="competition-a",
        starts_at=datetime(2026, 8, 14, 23, 0, tzinfo=timezone.utc),
        home_team=TeamRef("competition-a:home", "Home Team"),
        away_team=TeamRef("competition-a:away", "Away Team"),
    )


def _catalog() -> BroadcastCatalog:
    return BroadcastCatalog(
        {
            "radio-a": BroadcastStation(
                id="radio-a",
                label="Radio A",
                url="https://radio.example.com/",
                stream_url="https://stream.example.com/live.mp3",
                country="CL",
            )
        },
        {
            "competition-a": CompetitionBroadcastMapping(
                default_station_id="radio-a",
                team_station_ids={"competition-a:away": "radio-a"},
            )
        },
    )


def test_emits_a_versioned_playable_radio_suggestion():
    events = scheduled_matches_to_suggest_block_events(
        [_match()],
        _configuration(),
        broadcast_catalog=_catalog(),
    )

    assert len(events) == 1
    event = events[0]
    assert event.id == "suggest_block:sports-broadcast-v1:match-123:2026-08-14T23:00:00Z"
    assert event.data["externalContentId"] == "sports-broadcast-v1:match-123"
    assert event.data["title"] == "Home Team vs Away Team"
    assert "Radio preferida: Radio A" in event.data["description"]
    assert "sujeta a la programación" in event.data["description"]
    assert event.data["metadata"] == {
        "sport": "football",
        "team": "Away Team",
        "competition": "Competition A",
        "eventType": "match.scheduled",
        "source": "sports-addon",
        "startsAt": "2026-08-14T23:00:00Z",
        "radioLabel": "Radio A",
        "radioUrl": "https://radio.example.com/",
        "radioCountry": "CL",
        "stationName": "Radio A",
        "streamUrl": "https://stream.example.com/live.mp3",
        "broadcastCoverage": "preferred_station",
        "broadcastResolution": "team_preference",
    }


def test_falls_back_to_metadata_only_when_no_broadcast_mapping_exists():
    events = scheduled_matches_to_suggest_block_events([_match()], _configuration())

    metadata = events[0].data["metadata"]
    assert "streamUrl" not in metadata
    assert events[0].data["description"] == "Partido programado a las 19:00"
    assert not any(key.startswith("str") or key.startswith("idLeague") for key in metadata)
