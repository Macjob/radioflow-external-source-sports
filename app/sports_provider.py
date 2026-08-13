import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class Competition:
    id: str
    name: str
    country: str | None = None
    current_season: str | None = None


@dataclass(frozen=True)
class Team:
    id: str
    name: str


@dataclass(frozen=True)
class TeamRef:
    id: str
    name: str


@dataclass(frozen=True)
class ScheduledMatch:
    id: str
    competition_id: str
    starts_at: datetime
    home_team: TeamRef
    away_team: TeamRef
    venue: str | None = None
    status: Literal["scheduled"] = "scheduled"


@dataclass(frozen=True)
class ScheduledMatchOptions:
    starts_after: datetime
    starts_before: datetime


@dataclass(frozen=True)
class CompletedMatch:
    id: str
    competition_id: str
    starts_at: datetime
    home_team: TeamRef
    away_team: TeamRef
    home_score: int
    away_score: int
    status: Literal["finished"] = "finished"


@dataclass(frozen=True)
class CompletedMatchOptions:
    starts_after: datetime
    starts_before: datetime


class ProviderError(RuntimeError):
    """Base error exposed by SportsProvider implementations."""


class ProviderUnavailableError(ProviderError):
    pass


class ProviderRateLimitedError(ProviderError):
    pass


class ProviderInvalidResponseError(ProviderError):
    pass


class ProviderUnauthorizedError(ProviderError):
    pass


class SportsProvider(Protocol):
    @property
    def name(self) -> str: ...

    def get_competitions(self) -> list[Competition]: ...

    def get_teams(self, competition_id: str) -> list[Team]: ...

    def get_scheduled_matches(
        self,
        competition_id: str,
        options: ScheduledMatchOptions,
    ) -> list[ScheduledMatch]: ...

    def get_results(
        self,
        competition_id: str,
        options: CompletedMatchOptions,
    ) -> list[CompletedMatch]: ...


@runtime_checkable
class SyncableSportsProvider(Protocol):
    @property
    def has_data(self) -> bool: ...

    def sync_if_due(self, *, force: bool = False) -> bool: ...


def build_team_id(competition_id: str, name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug:
        raise ProviderInvalidResponseError("sports provider returned an invalid team name")
    return f"{competition_id}:{slug}"


def build_match_id(
    competition_id: str,
    starts_at: datetime,
    home_team_id: str,
    away_team_id: str,
) -> str:
    if starts_at.tzinfo is None:
        raise ProviderInvalidResponseError("scheduled match start must include a timezone")
    canonical = "|".join(
        [
            competition_id,
            starts_at.astimezone(timezone.utc).isoformat(),
            home_team_id,
            away_team_id,
        ]
    )
    return f"match-{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"
