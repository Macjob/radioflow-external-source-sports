from datetime import datetime, timezone

from app.config import Config
from app.models import RadioInfo, SportsEvent
from app.radioflow_blocks import to_radioflow_blocks


def _make_event(team: str, hour: int = 19, minute: int = 30) -> SportsEvent:
    dt = datetime(2026, 6, 10, hour, minute, tzinfo=timezone.utc).astimezone()
    return SportsEvent(
        id=f"match-{team}",
        title=f"{team} vs Other Team",
        team=team,
        starts_at=dt,
        timezone="America/Santiago",
        radio=RadioInfo(label="Test Radio", url="https://example.com"),
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
