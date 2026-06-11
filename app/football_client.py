import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"


class FootballDataClient:
    def __init__(self, api_key: str, timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"X-Auth-Token": self.api_key})
        return self._session

    def get_today_matches(self) -> list[dict[str, Any]]:
        session = self._get_session()
        url = f"{BASE_URL}/matches"
        logger.debug("Fetching today's matches from %s", url)
        try:
            resp = session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.ConnectionError as e:
            logger.error("Connection error while fetching matches: %s", e)
            return []
        except requests.Timeout as e:
            logger.error("Timeout while fetching matches: %s", e)
            return []
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            logger.error("HTTP error %s fetching matches: %s", status, e)
            if status == 403:
                logger.error("Invalid API key or forbidden access to football-data.org")
            return []
        except ValueError as e:
            logger.error("Invalid JSON response from football-data.org: %s", e)
            return []
        matches = data.get("matches", [])
        logger.info("Fetched %d matches from football-data.org", len(matches))
        return matches
