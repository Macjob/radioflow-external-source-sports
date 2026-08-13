import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.chile_sports.models import (
    ScheduleSnapshot,
    SourceAnnouncement,
    SourceCompetition,
    SourceDocument,
    SourceMatch,
    SourceTeam,
)
from app.chile_sports.normalization import normalized_team
from app.sports_provider import (
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)

DEFAULT_USER_AGENT = "RadioFlow-ChileSports/0.1 (+https://radioflow.media)"


class ScheduleSource(Protocol):
    name: str

    def fetch(self, if_modified_since: str | None = None) -> SourceDocument: ...

    def parse(
        self,
        document: SourceDocument,
        *,
        competition_id: str,
        competition_name: str,
        country: str,
        expected_season: str,
        external_competition_id: str,
    ) -> ScheduleSnapshot: ...


class AnnouncementSource(Protocol):
    name: str

    def fetch(self, since: datetime | None = None) -> list[SourceAnnouncement]: ...


def _stable_match_id(
    competition_id: str,
    season: str,
    matchweek: str,
    home_team_id: str,
    away_team_id: str,
) -> str:
    round_numbers = "-".join(re.findall(r"\d+", matchweek))
    matchweek_key = round_numbers or re.sub(r"\W+", "-", matchweek.casefold()).strip("-")
    canonical = "|".join([competition_id, season, matchweek_key, home_team_id, away_team_id])
    return f"match-{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


class CampeonatoChilenoScheduleSource:
    name = "campeonatochileno"

    def __init__(
        self,
        url: str,
        *,
        session: requests.Session | None = None,
        timeout: int = 15,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.url = url
        self.session = session or requests.Session()
        self.timeout = timeout
        self.user_agent = user_agent

    def fetch(self, if_modified_since: str | None = None) -> SourceDocument:
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        try:
            response = self.session.get(self.url, headers=headers, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as error:
            raise ProviderUnavailableError("Campeonato Chileno is unavailable") from error
        except requests.RequestException as error:
            raise ProviderUnavailableError("Campeonato Chileno request failed") from error
        fetched_at = datetime.now(timezone.utc)
        if response.status_code == 304:
            return SourceDocument(None, fetched_at, if_modified_since, not_modified=True)
        if response.status_code == 429:
            raise ProviderRateLimitedError("Campeonato Chileno rate limit reached")
        if response.status_code >= 500:
            raise ProviderUnavailableError("Campeonato Chileno is unavailable")
        if response.status_code != 200:
            raise ProviderInvalidResponseError(
                f"Campeonato Chileno returned HTTP {response.status_code}"
            )
        if "html" not in response.headers.get("content-type", "").casefold():
            raise ProviderInvalidResponseError("Campeonato Chileno returned non-HTML content")
        return SourceDocument(
            response.text,
            fetched_at,
            response.headers.get("last-modified"),
        )

    def parse(
        self,
        document: SourceDocument,
        *,
        competition_id: str,
        competition_name: str,
        country: str,
        expected_season: str,
        external_competition_id: str,
    ) -> ScheduleSnapshot:
        if not document.body:
            raise ProviderInvalidResponseError("Campeonato Chileno returned an empty document")
        soup = BeautifulSoup(document.body, "html.parser")
        title_node = soup.select_one(".competition-header__title")
        season_node = soup.select_one(".competition-header__sub-title")
        if not title_node or not season_node:
            raise ProviderInvalidResponseError("Campeonato Chileno competition header changed")
        source_competition_name = title_node.get_text(" ", strip=True)
        if not source_competition_name:
            raise ProviderInvalidResponseError("Campeonato Chileno returned an empty competition")
        season_match = re.search(r"\b(20\d{2})\b", season_node.get_text(" ", strip=True))
        if not season_match or season_match.group(1) != expected_season:
            raise ProviderInvalidResponseError("Campeonato Chileno returned an unexpected season")

        competition = SourceCompetition(
            id=competition_id,
            name=competition_name,
            country=country,
            season=expected_season,
            external_id=external_competition_id,
        )
        teams: dict[str, SourceTeam] = {}
        matches: list[SourceMatch] = []
        match_ids: set[str] = set()
        current_matchweek = ""
        nodes = soup.select(
            ".competition__matchweek-title, .anwp-fl-game[data-anwp-match][data-fl-game-datetime]"
        )
        for node in nodes:
            classes = set(node.get("class", []))
            if "competition__matchweek-title" in classes:
                current_matchweek = node.get_text(" ", strip=True)
                continue
            if not current_matchweek:
                raise ProviderInvalidResponseError("Campeonato Chileno matchweek marker changed")
            source_match = self._parse_match(
                node,
                competition_id=competition_id,
                season=expected_season,
                matchweek=current_matchweek,
            )
            if source_match.id in match_ids:
                raise ProviderInvalidResponseError("Campeonato Chileno returned duplicate matches")
            match_ids.add(source_match.id)
            matches.append(source_match)
            teams[source_match.home_team.id] = source_match.home_team
            teams[source_match.away_team.id] = source_match.away_team
        if not matches:
            raise ProviderInvalidResponseError("Campeonato Chileno returned no matches")
        return ScheduleSnapshot(
            competition,
            tuple(sorted(teams.values(), key=lambda item: item.name.casefold())),
            tuple(matches),
        )

    def _parse_match(
        self,
        node,
        *,
        competition_id: str,
        season: str,
        matchweek: str,
    ) -> SourceMatch:
        home_node = node.select_one(".match-slim__team-home-title")
        away_node = node.select_one(".match-slim__team-away-title")
        link_node = node.select_one('a[href*="/match/"]')
        if not home_node or not away_node or not link_node:
            raise ProviderInvalidResponseError("Campeonato Chileno match markup changed")
        home_id, home_name = normalized_team(competition_id, home_node.get_text(" ", strip=True))
        away_id, away_name = normalized_team(competition_id, away_node.get_text(" ", strip=True))
        home_team = SourceTeam(home_id, home_name, home_id.rsplit(":", 1)[-1])
        away_team = SourceTeam(away_id, away_name, away_id.rsplit(":", 1)[-1])

        raw_datetime = str(node.get("data-fl-game-datetime", "")).strip()
        try:
            local_start = datetime.fromisoformat(raw_datetime)
        except ValueError as error:
            raise ProviderInvalidResponseError("Campeonato Chileno returned an invalid kickoff") from error
        if local_start.tzinfo is None:
            raise ProviderInvalidResponseError("Campeonato Chileno kickoff has no timezone")
        time_node = node.select_one(".match__time-formatted")
        time_text = time_node.get_text(" ", strip=True) if time_node else ""
        time_confirmed = bool(re.search(r"\d{1,2}:\d{2}", time_text))
        starts_at = local_start.astimezone(timezone.utc) if time_confirmed else None

        note_node = node.select_one(".match-slim__bottom-special")
        note = note_node.get_text(" ", strip=True) if note_node else None
        status_class = next(
            (item for item in node.get("class", []) if item.startswith("game-status-")),
            "game-status-0",
        )
        status = "finished" if status_class == "game-status-1" else "scheduled"
        note_key = (note or "").casefold()
        if "suspend" in note_key:
            status = "suspended"
        elif any(token in note_key for token in ("aplaz", "posterg")):
            status = "postponed"

        home_score = self._score(node.select_one(".anwp-fl-game__scores-home"))
        away_score = self._score(node.select_one(".anwp-fl-game__scores-away"))
        if status == "finished" and (home_score is None or away_score is None):
            raise ProviderInvalidResponseError("Campeonato Chileno finished match has no score")
        venue_node = node.select_one(".match-slim__stadium")
        venue = venue_node.get_text(" ", strip=True) if venue_node else None
        source_url = urljoin(self.url, str(link_node.get("href", "")))
        if urlparse(source_url).netloc != urlparse(self.url).netloc:
            raise ProviderInvalidResponseError("Campeonato Chileno returned an external match URL")
        external_id = str(node.get("data-anwp-match", "")).strip()
        if not external_id:
            raise ProviderInvalidResponseError("Campeonato Chileno match has no source ID")
        internal_id = _stable_match_id(
            competition_id,
            season,
            matchweek,
            home_team.id,
            away_team.id,
        )
        return SourceMatch(
            id=internal_id,
            external_id=external_id,
            competition_id=competition_id,
            season=season,
            matchweek=matchweek,
            source_date=local_start.date(),
            starts_at=starts_at,
            time_confirmed=time_confirmed,
            home_team=home_team,
            away_team=away_team,
            venue=venue or None,
            status=status,
            home_score=home_score,
            away_score=away_score,
            source_url=source_url,
            note=note,
        )

    @staticmethod
    def _score(node) -> int | None:
        if not node:
            return None
        value = node.get_text(" ", strip=True)
        return int(value) if value.isdigit() else None


class AnfpAnnouncementSource:
    name = "anfp"
    _CHANGE_TERMS = {
        "reprogram": "reprogrammed",
        "cambio de horario": "reprogrammed",
        "no autoriz": "reprogrammed",
        "suspend": "suspended",
        "aplaz": "postponed",
        "posterg": "postponed",
    }

    def __init__(
        self,
        api_url: str,
        *,
        session: requests.Session | None = None,
        timeout: int = 15,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.api_url = api_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.user_agent = user_agent

    def fetch(self, since: datetime | None = None) -> list[SourceAnnouncement]:
        modified_after = (since or datetime.now(timezone.utc) - timedelta(days=30)).astimezone(timezone.utc)
        page = 1
        announcements: list[SourceAnnouncement] = []
        while True:
            params = {
                "per_page": 100,
                "page": page,
                "orderby": "modified",
                "order": "asc",
                "modified_after": modified_after.isoformat().replace("+00:00", "Z"),
                "_fields": "id,date_gmt,modified_gmt,slug,link,title,content",
            }
            try:
                response = self.session.get(
                    self.api_url,
                    params=params,
                    headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                raise ProviderUnavailableError("ANFP announcements are unavailable") from error
            except requests.RequestException as error:
                raise ProviderUnavailableError("ANFP announcement request failed") from error
            if response.status_code == 400 and page > 1:
                break
            if response.status_code == 429:
                raise ProviderRateLimitedError("ANFP rate limit reached")
            if response.status_code >= 500:
                raise ProviderUnavailableError("ANFP announcements are unavailable")
            if response.status_code != 200:
                raise ProviderInvalidResponseError(f"ANFP returned HTTP {response.status_code}")
            try:
                rows = response.json()
            except ValueError as error:
                raise ProviderInvalidResponseError("ANFP returned invalid JSON") from error
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ProviderInvalidResponseError("ANFP returned an invalid post collection")
            announcements.extend(self._parse_row(row) for row in rows)
            total_pages = int(response.headers.get("x-wp-totalpages", "1"))
            if page >= total_pages:
                break
            page += 1
        return announcements

    def _parse_row(self, row: dict) -> SourceAnnouncement:
        try:
            published_at = datetime.fromisoformat(f"{row['date_gmt']}+00:00")
            modified_at = datetime.fromisoformat(f"{row['modified_gmt']}+00:00")
            external_id = str(row["id"])
            url = str(row["link"])
            title_html = str(row["title"]["rendered"])
            content_html = str(row["content"]["rendered"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderInvalidResponseError("ANFP returned an incomplete post") from error
        title = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        content = BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True)
        searchable = f"{title} {content}".casefold()
        change_type = next(
            (kind for token, kind in self._CHANGE_TERMS.items() if token in searchable),
            None,
        )
        return SourceAnnouncement(
            external_id,
            title,
            published_at,
            modified_at,
            url,
            content,
            change_type,
        )
