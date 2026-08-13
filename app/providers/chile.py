from datetime import timezone

from app.chile_sports.storage import ChileSportsStore
from app.chile_sports.sync import ChileSportsSyncService
from app.sports_provider import (
    Competition,
    CompletedMatch,
    CompletedMatchOptions,
    ScheduledMatch,
    ScheduledMatchOptions,
    Team,
)


class ChileSportsProvider:
    def __init__(self, store: ChileSportsStore, sync_service: ChileSportsSyncService):
        self.store = store
        self.sync_service = sync_service

    @property
    def name(self) -> str:
        return "chile"

    @property
    def has_data(self) -> bool:
        return self.store.has_data()

    def sync_if_due(self, *, force: bool = False) -> bool:
        return self.sync_service.sync_if_due(force=force)

    def get_competitions(self) -> list[Competition]:
        return self.store.get_competitions()

    def get_teams(self, competition_id: str) -> list[Team]:
        self._require_competition(competition_id)
        return self.store.get_teams(competition_id)

    def get_scheduled_matches(
        self,
        competition_id: str,
        options: ScheduledMatchOptions,
    ) -> list[ScheduledMatch]:
        self._validate_range(options.starts_after, options.starts_before)
        self._require_competition(competition_id)
        if options.starts_before <= options.starts_after:
            return []
        return self.store.get_scheduled_matches(
            competition_id,
            options.starts_after.astimezone(timezone.utc),
            options.starts_before.astimezone(timezone.utc),
        )

    def get_results(
        self,
        competition_id: str,
        options: CompletedMatchOptions,
    ) -> list[CompletedMatch]:
        self._validate_range(options.starts_after, options.starts_before)
        self._require_competition(competition_id)
        if options.starts_before <= options.starts_after:
            return []
        return self.store.get_results(
            competition_id,
            options.starts_after.astimezone(timezone.utc),
            options.starts_before.astimezone(timezone.utc),
        )

    def _require_competition(self, competition_id: str):
        if not any(item.id == competition_id for item in self.store.get_competitions()):
            raise ValueError("unknown competition")

    @staticmethod
    def _validate_range(starts_after, starts_before):
        if starts_after.tzinfo is None or starts_before.tzinfo is None:
            raise ValueError("match filters must be timezone-aware")
