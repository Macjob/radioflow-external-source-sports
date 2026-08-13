import logging
import threading
from datetime import datetime, timedelta, timezone

from app.chile_sports.sources import (
    AnnouncementSource,
    ScheduleSource,
)
from app.chile_sports.storage import ChileSportsStore
from app.sports_provider import ProviderError, ProviderInvalidResponseError

logger = logging.getLogger(__name__)


class ChileSportsSyncService:
    def __init__(
        self,
        store: ChileSportsStore,
        schedule_source: ScheduleSource,
        announcement_source: AnnouncementSource | None,
        *,
        competition_id: str,
        competition_name: str,
        country: str,
        season: str,
        external_competition_id: str,
        expected_team_count: int = 16,
        expected_match_count: int = 240,
        regular_interval: timedelta = timedelta(days=1),
        near_match_interval: timedelta = timedelta(hours=4),
        near_match_window: timedelta = timedelta(days=7),
    ):
        self.store = store
        self.schedule_source = schedule_source
        self.announcement_source = announcement_source
        self.competition_id = competition_id
        self.competition_name = competition_name
        self.country = country
        self.season = season
        self.external_competition_id = external_competition_id
        self.expected_team_count = expected_team_count
        self.expected_match_count = expected_match_count
        self.regular_interval = regular_interval
        self.near_match_interval = near_match_interval
        self.near_match_window = near_match_window
        self._lock = threading.Lock()

    def sync_if_due(self, *, force: bool = False) -> bool:
        now = datetime.now(timezone.utc)
        if not force and not self._is_due(now):
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._sync_schedule(now)
            self._sync_announcements(now)
            return True
        finally:
            self._lock.release()

    def _is_due(self, now: datetime) -> bool:
        state = self.store.sync_state(self.schedule_source.name)
        if not state or not state.get("last_success_at"):
            return True
        last_success = datetime.fromisoformat(state["last_success_at"]).astimezone(timezone.utc)
        next_match = self.store.next_scheduled_start(now)
        interval = self.regular_interval
        if next_match and next_match <= now + self.near_match_window:
            interval = self.near_match_interval
        return now - last_success >= interval

    def _sync_schedule(self, now: datetime):
        state = self.store.sync_state(self.schedule_source.name) or {}
        logger.info("Chile sports sync started: source=%s", self.schedule_source.name)
        try:
            document = self.schedule_source.fetch(state.get("last_modified"))
            if document.not_modified:
                self.store.record_not_modified(self.schedule_source.name, document.fetched_at)
                logger.info("Chile sports sync completed: source=%s not_modified=true", self.schedule_source.name)
                return
            snapshot = self.schedule_source.parse(
                document,
                competition_id=self.competition_id,
                competition_name=self.competition_name,
                country=self.country,
                expected_season=self.season,
                external_competition_id=self.external_competition_id,
            )
            if len(snapshot.teams) < self.expected_team_count:
                raise ProviderInvalidResponseError(
                    f"Campeonato Chileno returned only {len(snapshot.teams)} teams"
                )
            if len(snapshot.matches) < self.expected_match_count:
                raise ProviderInvalidResponseError(
                    f"Campeonato Chileno returned only {len(snapshot.matches)} matches"
                )
            discovered, changed = self.store.store_snapshot(
                snapshot,
                source=self.schedule_source.name,
                fetched_at=document.fetched_at,
                last_modified=document.last_modified,
            )
            logger.info(
                "Chile sports sync completed: source=%s matches_discovered=%d matches_changed=%d total=%d",
                self.schedule_source.name,
                discovered,
                changed,
                len(snapshot.matches),
            )
        except ProviderError as error:
            self.store.record_failure(self.schedule_source.name, now, str(error))
            logger.error("Chile sports sync failed: source=%s error=%s", self.schedule_source.name, error)
            raise

    def _sync_announcements(self, now: datetime):
        if self.announcement_source is None:
            return
        state = self.store.sync_state(self.announcement_source.name) or {}
        since = None
        if state.get("last_success_at"):
            since = datetime.fromisoformat(state["last_success_at"]).astimezone(timezone.utc)
        try:
            announcements = self.announcement_source.fetch(since)
            self.store.store_announcements(
                announcements,
                source=self.announcement_source.name,
                fetched_at=now,
            )
            candidates = sum(1 for item in announcements if item.change_type)
            logger.info(
                "Chile sports announcement sync completed: source=%s posts=%d change_candidates=%d",
                self.announcement_source.name,
                len(announcements),
                candidates,
            )
        except ProviderError as error:
            self.store.record_failure(self.announcement_source.name, now, str(error))
            logger.warning(
                "Chile sports announcement sync failed without discarding schedule data: source=%s error=%s",
                self.announcement_source.name,
                error,
            )
