from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import SportsEvent

ADDON_ID = "app.radioflow.sports"
ADDON_VERSION = "0.1.0"


class AddonConfiguration(BaseModel):
    supported: Literal[False] = False


class AddonEndpoints(BaseModel):
    health: str = "/health"
    events: str = "/addon/events"


class AddonManifest(BaseModel):
    manifest_version: Literal[1] = Field(default=1, alias="manifestVersion")
    id: str
    name: str
    description: str
    version: str
    author: str
    capabilities: list[Literal["notifications", "suggest_blocks"]]
    events: list[str]
    configuration: AddonConfiguration
    endpoints: AddonEndpoints


class AddonHealth(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str


class AddonEventEnvelope(BaseModel):
    id: str
    type: str
    timestamp: datetime
    source: str
    data: dict[str, Any]


SPORTS_ADDON_MANIFEST = AddonManifest(
    id=ADDON_ID,
    name="Sports Notifications",
    description="Scheduled sports events from the hosted RadioFlow service.",
    version=ADDON_VERSION,
    author="RadioFlow",
    capabilities=["notifications", "suggest_blocks"],
    events=["match.scheduled"],
    configuration=AddonConfiguration(),
    endpoints=AddonEndpoints(),
)


def to_addon_event(event: SportsEvent, duration_minutes: int) -> AddonEventEnvelope:
    starts_at = event.starts_at.isoformat()
    radio = None
    if event.radio:
        radio = {
            "label": event.radio.label,
            "url": event.radio.url,
            "streamUrl": event.radio.stream_url,
            "country": event.radio.country,
        }
    return AddonEventEnvelope(
        id=f"match.scheduled:{event.id}:{starts_at}",
        type="match.scheduled",
        timestamp=event.starts_at,
        source=ADDON_ID,
        data={
            "matchId": event.id,
            "title": event.title,
            "team": event.team,
            "startsAt": starts_at,
            "endsAt": (event.starts_at + timedelta(minutes=duration_minutes)).isoformat(),
            "timezone": event.timezone,
            "provider": event.source,
            "radio": radio,
        },
    )
