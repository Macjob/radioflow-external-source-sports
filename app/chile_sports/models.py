from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

SourceMatchStatus = Literal["scheduled", "finished", "postponed", "suspended"]


@dataclass(frozen=True)
class SourceCompetition:
    id: str
    name: str
    country: str
    season: str
    external_id: str


@dataclass(frozen=True)
class SourceTeam:
    id: str
    name: str
    external_id: str


@dataclass(frozen=True)
class SourceMatch:
    id: str
    external_id: str
    competition_id: str
    season: str
    matchweek: str
    source_date: date
    starts_at: datetime | None
    time_confirmed: bool
    home_team: SourceTeam
    away_team: SourceTeam
    venue: str | None
    status: SourceMatchStatus
    home_score: int | None
    away_score: int | None
    source_url: str
    note: str | None = None


@dataclass(frozen=True)
class ScheduleSnapshot:
    competition: SourceCompetition
    teams: tuple[SourceTeam, ...]
    matches: tuple[SourceMatch, ...]


@dataclass(frozen=True)
class SourceDocument:
    body: str | None
    fetched_at: datetime
    last_modified: str | None = None
    not_modified: bool = False


@dataclass(frozen=True)
class SourceAnnouncement:
    external_id: str
    title: str
    published_at: datetime
    modified_at: datetime
    url: str
    content: str
    change_type: str | None
