from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    ExternalBlockAction,
    RadioflowExternalBlock,
    RadioInfo,
    SportsEvent,
)


class TestRadioInfo:
    def test_valid(self):
        r = RadioInfo(label="Test FM", url="https://example.com")
        assert r.label == "Test FM"
        assert r.url == "https://example.com"

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            RadioInfo()


class TestSportsEvent:
    def test_valid(self):
        dt = datetime(2026, 6, 10, 19, 30, tzinfo=timezone.utc)
        event = SportsEvent(
            id="match-123",
            title="Colo-Colo vs U. de Chile",
            team="Colo-Colo",
            starts_at=dt,
            timezone="America/Santiago",
            radio=RadioInfo(label="FM", url="https://example.com"),
        )
        assert event.type == "sports_event"
        assert event.source == "football-data.org"

    def test_minimal(self):
        dt = datetime(2026, 6, 10, 19, 30, tzinfo=timezone.utc)
        event = SportsEvent(
            id="match-1",
            title="Test",
            team="Test",
            starts_at=dt,
            timezone="UTC",
        )
        assert event.radio is None


class TestExternalBlockAction:
    def test_valid(self):
        a = ExternalBlockAction(type="open_stream", label="Escuchar", url="https://example.com")
        assert a.type == "open_stream"


class TestRadioflowExternalBlock:
    def test_valid(self):
        block = RadioflowExternalBlock(
            external_id="sports-match-123",
            title="Hoy juega Colo-Colo",
            description="Colo-Colo vs U. de Chile a las 19:30",
            start_time="2026-06-10T19:30:00-04:00",
            duration_minutes=120,
            action=ExternalBlockAction(type="open_stream", label="Escuchar", url="https://example.com"),
            metadata={"sport": "football", "team": "Colo-Colo", "source": "football-data.org"},
        )
        assert block.provider == "sports-notifier"
        assert block.kind == "external_audio_recommendation"

    def test_default_metadata(self):
        block = RadioflowExternalBlock(
            external_id="sports-match-1",
            title="Test",
            description="Test",
            start_time="2026-06-10T19:30:00Z",
            duration_minutes=120,
            action=ExternalBlockAction(type="open_stream", label="X", url="https://x.com"),
        )
        assert block.metadata == {}
