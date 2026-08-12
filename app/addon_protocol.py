from datetime import datetime
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


def to_addon_event(event: SportsEvent) -> AddonEventEnvelope:
    starts_at = event.starts_at.isoformat()
    return AddonEventEnvelope(
        id=f"match.scheduled:{event.id}:{starts_at}",
        type="match.scheduled",
        timestamp=event.starts_at,
        source=ADDON_ID,
        data=event.model_dump(mode="json"),
    )
