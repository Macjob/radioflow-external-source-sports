from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RadioInfo(BaseModel):
    label: str
    url: str
    stream_url: str | None = Field(default=None, alias="streamUrl")


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


class RadioflowExternalSuggestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_key: str = Field(alias="sourceKey")
    external_content_id: str = Field(alias="externalContentId")
    title: str
    description: str
    suggested_date: str = Field(alias="suggestedDate")
    suggested_start_time: str = Field(alias="suggestedStartTime")
    suggested_end_time: str = Field(alias="suggestedEndTime")
    content_kind: Literal["metadata_only"] = Field(default="metadata_only", alias="contentKind")
    content_mode: Literal["reference_only"] = Field(default="reference_only", alias="contentMode")
    render_mode: Literal["display_card"] = Field(default="display_card", alias="renderMode")
    fallback_strategy: Literal["skip"] = Field(default="skip", alias="fallbackStrategy")
    conflict_policy: Literal["reject"] = Field(default="reject", alias="conflictPolicy")
    metadata: dict[str, Any] = Field(default_factory=dict)
