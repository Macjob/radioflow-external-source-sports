from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RadioInfo(BaseModel):
    label: str
    url: str


class CountryConfig(BaseModel):
    teams: list[str]
    team_mapping: dict[str, list[str]] = {}
    radios: dict[str, RadioInfo]
    default_radio: RadioInfo | None = None


class SportsEvent(BaseModel):
    id: str
    type: str = "sports_event"
    title: str
    team: str
    starts_at: datetime
    timezone: str
    source: str = "football-data.org"
    radio: RadioInfo | None = None


class ExternalBlockAction(BaseModel):
    type: str
    label: str
    url: str


class RadioflowExternalBlock(BaseModel):
    external_id: str
    provider: str = "sports-notifier"
    kind: str = "external_audio_recommendation"
    title: str
    description: str
    start_time: str
    duration_minutes: int
    action: ExternalBlockAction
    metadata: dict[str, Any] = Field(default_factory=dict)
