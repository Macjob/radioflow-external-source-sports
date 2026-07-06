from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import Config
from app.models import RadioInfo, SportsEvent
from app.radioflow_blocks import to_radioflow_blocks, to_radioflow_suggestions


def _make_event(
    team: str,
    hour: int = 19,
    minute: int = 30,
    radio: RadioInfo | None = None,
) -> SportsEvent:
    dt = datetime(2026, 6, 10, hour, minute, tzinfo=timezone.utc).astimezone()
    return SportsEvent(
        id=f"match-{team}",
        title=f"{team} vs Other Team",
        team=team,
        starts_at=dt,
        timezone="America/Santiago",
        radio=radio or RadioInfo(label="Test Radio", url="https://example.com"),
    )


def _make_config() -> Config:
    return Config(
        timezone="America/Santiago",
        notification_window_minutes=30,
        default_match_duration_minutes=120,
        teams=["Colo-Colo"],
        team_mapping={"Colo-Colo": ["Colo-Colo"]},
        radios={"Colo-Colo": RadioInfo(label="Test Radio", url="https://example.com")},
    )


class TestToRadioflowBlocks:
    def test_single_event(self):
        event = _make_event("Colo-Colo")
        config = _make_config()
        blocks = to_radioflow_blocks([event], config)

        assert len(blocks) == 1
        block = blocks[0]

        assert block.external_id == "sports-match-Colo-Colo"
        assert block.provider == "sports-notifier"
        assert block.kind == "external_audio_recommendation"
        assert block.title == "Hoy juega Colo-Colo"
        assert "Colo-Colo vs Other Team" in block.description
        assert block.duration_minutes == 120
        assert block.action.type == "open_stream"
        assert "Test Radio" in block.action.label
        assert block.action.url == "https://example.com"
        assert block.metadata["sport"] == "football"
        assert block.metadata["team"] == "Colo-Colo"

    def test_multiple_events(self):
        config = _make_config()
        events = [_make_event("Colo-Colo", 19, 30), _make_event("Colo-Colo", 22, 0)]
        blocks = to_radioflow_blocks(events, config)
        assert len(blocks) == 2

    def test_empty_events(self):
        config = _make_config()
        blocks = to_radioflow_blocks([], config)
        assert blocks == []

    def test_event_without_radio(self):
        config = _make_config()
        event = _make_event("Colo-Colo")
        event.radio = None
        blocks = to_radioflow_blocks([event], config)
        assert blocks[0].action.label == "Sin radio asignada"


class TestToRadioflowSuggestions:
    def test_single_event_maps_to_radioflow_v0_suggestion_payload(self):
        event = _make_event("Colo-Colo", 19, 30)
        config = _make_config()
        suggestions = to_radioflow_suggestions([event], config, source_key="sports-test")

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        payload = suggestion.model_dump(by_alias=True)

        assert payload["sourceKey"] == "sports-test"
        assert payload["externalContentId"] == "sports-match-Colo-Colo"
        assert payload["title"] == "Hoy juega Colo-Colo"
        assert "Colo-Colo vs Other Team" in payload["description"]
        expected_start = event.starts_at.astimezone(ZoneInfo(config.timezone))
        expected_end = expected_start + timedelta(minutes=config.default_match_duration_minutes)
        assert payload["suggestedDate"] == expected_start.date().isoformat()
        assert payload["suggestedStartTime"] == expected_start.strftime("%H:%M")
        assert payload["suggestedEndTime"] == expected_end.strftime("%H:%M")
        assert payload["contentKind"] == "metadata_only"
        assert payload["contentMode"] == "reference_only"
        assert payload["renderMode"] == "display_card"
        assert payload["fallbackStrategy"] == "skip"
        assert payload["conflictPolicy"] == "reject"
        assert payload["metadata"]["sport"] == "football"
        assert payload["metadata"]["team"] == "Colo-Colo"
        assert payload["metadata"]["radioLabel"] == "Test Radio"
        assert payload["metadata"]["radioUrl"] == "https://example.com"

    def test_empty_events_map_to_empty_suggestions(self):
        config = _make_config()
        assert to_radioflow_suggestions([], config, source_key="sports-test") == []

    def test_event_with_stream_url_adds_resolved_radio_metadata(self):
        event = _make_event(
            "Colo-Colo",
            radio=RadioInfo(
                label="Test Radio",
                url="https://example.com",
                streamUrl="https://stream.example.com/test.aac",
            ),
        )
        config = _make_config()
        suggestions = to_radioflow_suggestions([event], config, source_key="sports-test")

        metadata = suggestions[0].model_dump(by_alias=True)["metadata"]
        assert metadata["radioLabel"] == "Test Radio"
        assert metadata["radioUrl"] == "https://example.com"
        assert metadata["stationName"] == "Test Radio"
        assert metadata["streamUrl"] == "https://stream.example.com/test.aac"
