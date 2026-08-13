from datetime import datetime, timezone

import requests

from app.provider_cache import SingleFlightTTLCache
from app.provider_config import CompetitionCatalogEntry
from app.sports_provider import (
    Competition,
    CompletedMatch,
    CompletedMatchOptions,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderUnauthorizedError,
    ProviderUnavailableError,
    ScheduledMatch,
    ScheduledMatchOptions,
    Team,
    TeamRef,
    build_match_id,
    build_team_id,
)

TEAMS_CACHE_TTL_SECONDS = 6 * 60 * 60
FIXTURES_CACHE_TTL_SECONDS = 30 * 60
SCHEDULED_STATUSES = {"ns", "not started", "scheduled", "tbd"}
FINISHED_STATUSES = {"ft", "finished", "match finished"}


class TheSportsDBProvider:
    def __init__(
        self,
        api_key: str,
        catalog: tuple[CompetitionCatalogEntry, ...],
        *,
        session: requests.Session | None = None,
        cache: SingleFlightTTLCache | None = None,
        timeout: int = 10,
        base_url: str = "https://www.thesportsdb.com/api/v1/json",
    ):
        if not api_key:
            raise ValueError("THESPORTSDB_API_KEY is required")
        self.api_key = api_key
        self.catalog = tuple(entry for entry in catalog if self.name in entry.providers)
        self.session = session or requests.Session()
        self.cache = cache or SingleFlightTTLCache()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "thesportsdb"

    def get_competitions(self) -> list[Competition]:
        return [
            Competition(
                id=entry.id,
                name=entry.name,
                country=entry.country,
                current_season=entry.current_season,
            )
            for entry in self.catalog
        ]

    def get_teams(self, competition_id: str) -> list[Team]:
        entry = self._competition(competition_id)
        return list(
            self.cache.get_or_load(
                f"{self.name}:normalized-teams:{entry.id}:{entry.current_season}",
                TEAMS_CACHE_TTL_SECONDS,
                lambda: tuple(self._load_teams(entry)),
            )
        )

    def _load_teams(self, entry: CompetitionCatalogEntry) -> list[Team]:
        mapping = entry.providers[self.name]
        catalog_rows = self.cache.get_or_load(
            f"{self.name}:teams:{mapping.league_name}",
            TEAMS_CACHE_TTL_SECONDS,
            lambda: tuple(
                self._fetch_rows(
                    "search_all_teams.php",
                    {"l": mapping.league_name.replace(" ", "_")},
                    "teams",
                )
            ),
        )
        provider_teams = [
            str(row.get("strTeam", "")).strip()
            for row in catalog_rows
            if str(row.get("idLeague", "")).strip() == mapping.league_id
        ]
        for row in self._season_rows(entry):
            provider_teams.extend(
                [str(row.get("strHomeTeam", "")).strip(), str(row.get("strAwayTeam", "")).strip()]
            )
        teams = {}
        for name in provider_teams:
            if not name:
                continue
            internal_id = build_team_id(entry.id, name)
            existing = teams.get(internal_id)
            if existing and existing.name != name:
                raise ProviderInvalidResponseError("sports provider returned colliding team identities")
            teams[internal_id] = Team(id=internal_id, name=name)
        return sorted(teams.values(), key=lambda team: team.name.casefold())

    def get_scheduled_matches(
        self,
        competition_id: str,
        options: ScheduledMatchOptions,
    ) -> list[ScheduledMatch]:
        if options.starts_after.tzinfo is None or options.starts_before.tzinfo is None:
            raise ValueError("scheduled match filters must be timezone-aware")
        if options.starts_before <= options.starts_after:
            return []
        entry = self._competition(competition_id)
        mapping = entry.providers[self.name]
        season_rows = self._season_rows(entry)
        next_rows = self.cache.get_or_load(
            f"{self.name}:next:{mapping.league_id}",
            FIXTURES_CACHE_TTL_SECONDS,
            lambda: tuple(self._fetch_rows("eventsnextleague.php", {"id": mapping.league_id}, "events")),
        )
        rows = (*season_rows, *next_rows)
        starts_after = options.starts_after.astimezone(timezone.utc)
        starts_before = options.starts_before.astimezone(timezone.utc)
        matches: dict[str, ScheduledMatch] = {}
        for row in rows:
            status = str(row.get("strStatus", "")).strip().casefold()
            postponed = str(row.get("strPostponed", "")).strip().casefold()
            if status not in SCHEDULED_STATUSES or postponed in {"1", "true", "yes"}:
                continue
            starts_at = self._parse_utc_start(row)
            if not starts_after <= starts_at <= starts_before:
                continue
            home_name = str(row.get("strHomeTeam", "")).strip()
            away_name = str(row.get("strAwayTeam", "")).strip()
            if not home_name or not away_name:
                raise ProviderInvalidResponseError("sports provider returned an incomplete scheduled match")
            home_team_id = build_team_id(entry.id, home_name)
            away_team_id = build_team_id(entry.id, away_name)
            match_id = build_match_id(entry.id, starts_at, home_team_id, away_team_id)
            matches[match_id] = ScheduledMatch(
                id=match_id,
                competition_id=entry.id,
                starts_at=starts_at,
                home_team=TeamRef(home_team_id, home_name),
                away_team=TeamRef(away_team_id, away_name),
            )
        return sorted(matches.values(), key=lambda match: match.starts_at)

    def get_results(
        self,
        competition_id: str,
        options: CompletedMatchOptions,
    ) -> list[CompletedMatch]:
        if options.starts_after.tzinfo is None or options.starts_before.tzinfo is None:
            raise ValueError("completed match filters must be timezone-aware")
        if options.starts_before <= options.starts_after:
            return []
        entry = self._competition(competition_id)
        starts_after = options.starts_after.astimezone(timezone.utc)
        starts_before = options.starts_before.astimezone(timezone.utc)
        matches: dict[str, CompletedMatch] = {}
        for row in self._season_rows(entry):
            status = str(row.get("strStatus", "")).strip().casefold()
            if status not in FINISHED_STATUSES:
                continue
            starts_at = self._parse_utc_start(row)
            if not starts_after <= starts_at <= starts_before:
                continue
            home_name = str(row.get("strHomeTeam", "")).strip()
            away_name = str(row.get("strAwayTeam", "")).strip()
            try:
                home_score = int(row["intHomeScore"])
                away_score = int(row["intAwayScore"])
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderInvalidResponseError(
                    "sports provider returned an incomplete finished match"
                ) from error
            home_team_id = build_team_id(entry.id, home_name)
            away_team_id = build_team_id(entry.id, away_name)
            match_id = build_match_id(entry.id, starts_at, home_team_id, away_team_id)
            matches[match_id] = CompletedMatch(
                id=match_id,
                competition_id=entry.id,
                starts_at=starts_at,
                home_team=TeamRef(home_team_id, home_name),
                away_team=TeamRef(away_team_id, away_name),
                home_score=home_score,
                away_score=away_score,
            )
        return sorted(matches.values(), key=lambda match: match.starts_at)

    def _season_rows(self, entry: CompetitionCatalogEntry) -> tuple[dict, ...]:
        mapping = entry.providers[self.name]
        return self.cache.get_or_load(
            f"{self.name}:season:{mapping.league_id}:{entry.current_season}",
            FIXTURES_CACHE_TTL_SECONDS,
            lambda: tuple(
                self._fetch_rows(
                    "eventsseason.php",
                    {"id": mapping.league_id, "s": entry.current_season},
                    "events",
                )
            ),
        )

    def _competition(self, competition_id: str) -> CompetitionCatalogEntry:
        entry = next((item for item in self.catalog if item.id == competition_id), None)
        if not entry:
            raise ValueError("unknown competition")
        return entry

    def _fetch_rows(self, endpoint: str, params: dict[str, str], collection: str) -> list[dict]:
        try:
            response = self.session.get(
                f"{self.base_url}/{self.api_key}/{endpoint}",
                params=params,
                timeout=self.timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            raise ProviderUnavailableError("sports provider is unavailable") from error
        except requests.RequestException as error:
            raise ProviderUnavailableError("sports provider request failed") from error
        if response.status_code in {401, 403}:
            raise ProviderUnauthorizedError("sports provider rejected its credential")
        if response.status_code == 429:
            raise ProviderRateLimitedError("sports provider rate limit reached")
        if response.status_code >= 500:
            raise ProviderUnavailableError("sports provider is unavailable")
        if response.status_code >= 400:
            raise ProviderInvalidResponseError("sports provider rejected the request")
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderInvalidResponseError("sports provider returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError("sports provider returned an invalid payload")
        rows = payload.get(collection)
        if rows is None:
            return []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderInvalidResponseError("sports provider returned an invalid collection")
        return rows

    @staticmethod
    def _parse_utc_start(row: dict) -> datetime:
        date_value = str(row.get("dateEvent", "")).strip()
        time_value = str(row.get("strTime", "")).strip()
        utc_value: datetime | None = None
        if date_value and time_value:
            try:
                utc_value = datetime.fromisoformat(f"{date_value}T{time_value}").replace(tzinfo=timezone.utc)
            except ValueError as error:
                raise ProviderInvalidResponseError("sports provider returned an invalid UTC date or time") from error

        timestamp_value = str(row.get("strTimestamp", "")).strip()
        timestamp: datetime | None = None
        if timestamp_value:
            try:
                timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ProviderInvalidResponseError("sports provider returned an invalid timestamp") from error
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(timezone.utc)

        if utc_value is not None:
            if timestamp is not None and timestamp.tzinfo is not None:
                if abs((timestamp - utc_value).total_seconds()) > 60:
                    raise ProviderInvalidResponseError("sports provider returned conflicting UTC timestamps")
            elif timestamp is not None and timestamp.replace(tzinfo=timezone.utc) != utc_value:
                raise ProviderInvalidResponseError("sports provider returned conflicting timestamps")
            return utc_value
        if timestamp is not None and timestamp.tzinfo is not None:
            return timestamp
        raise ProviderInvalidResponseError("sports provider did not return an unambiguous UTC start")
