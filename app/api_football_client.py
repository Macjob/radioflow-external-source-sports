import logging
import time
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
CACHE_TTL_SECONDS = 15 * 60


class ApiFootballClient:
    def __init__(self, api_key: str, timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def get_leagues(self, country: str = "Chile") -> list[dict[str, Any]]:
        return self._get("leagues", {"country": country}, cache_ttl=6 * 60 * 60)

    def get_teams(self, league_id: int, season: int) -> list[dict[str, Any]]:
        return self._get("teams", {"league": str(league_id), "season": str(season)}, cache_ttl=6 * 60 * 60)

    def get_fixtures(
        self,
        team_id: int,
        from_date: date,
        to_date: date,
        timezone: str,
    ) -> list[dict[str, Any]]:
        return self._get(
            "fixtures",
            {
                "team": str(team_id),
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "timezone": timezone,
                "status": "NS-TBD",
            },
            cache_ttl=5 * 60,
        )

    def _get(
        self,
        endpoint: str,
        params: dict[str, str],
        cache_ttl: int = CACHE_TTL_SECONDS,
    ) -> list[dict[str, Any]]:
        cache_key = f"{endpoint}?" + "&".join(f"{key}={params[key]}" for key in sorted(params))
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < cache_ttl:
            return cached[1]

        try:
            response = requests.get(
                f"{BASE_URL}/{endpoint}",
                params=params,
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as error:
            logger.error("API-Football request failed for %s: %s", endpoint, error)
            return []

        errors = payload.get("errors")
        if errors:
            logger.error("API-Football returned errors for %s", endpoint)
            return []
        rows = payload.get("response", [])
        if not isinstance(rows, list):
            logger.error("API-Football returned an invalid response for %s", endpoint)
            return []
        remaining = response.headers.get("x-ratelimit-requests-remaining")
        if remaining is not None:
            logger.info("API-Football %s request succeeded; daily remaining=%s", endpoint, remaining)
        self._cache[cache_key] = (now, rows)
        return rows
