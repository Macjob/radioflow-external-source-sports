import os
from collections.abc import Callable, Mapping
from datetime import timedelta

import requests

from app.chile_sports.sources import (
    AnfpAnnouncementSource,
    CampeonatoChilenoScheduleSource,
)
from app.chile_sports.storage import ChileSportsStore
from app.chile_sports.sync import ChileSportsSyncService
from app.provider_cache import SingleFlightTTLCache
from app.provider_config import CompetitionCatalogEntry, load_competition_catalog
from app.providers.chile import ChileSportsProvider
from app.providers.thesportsdb import TheSportsDBProvider
from app.sports_provider import SportsProvider

ProviderFactory = Callable[
    [Mapping[str, str], tuple[CompetitionCatalogEntry, ...], requests.Session | None, SingleFlightTTLCache | None],
    SportsProvider,
]


def _create_thesportsdb(
    environment: Mapping[str, str],
    catalog: tuple[CompetitionCatalogEntry, ...],
    session: requests.Session | None,
    cache: SingleFlightTTLCache | None,
) -> SportsProvider:
    return TheSportsDBProvider(
        api_key=environment.get("THESPORTSDB_API_KEY", "123").strip(),
        catalog=catalog,
        session=session,
        cache=cache,
        base_url=environment.get("THESPORTSDB_BASE_URL", "https://www.thesportsdb.com/api/v1/json"),
    )


def _create_chile(
    environment: Mapping[str, str],
    catalog: tuple[CompetitionCatalogEntry, ...],
    session: requests.Session | None,
    cache: SingleFlightTTLCache | None,
) -> SportsProvider:
    del cache
    entries = tuple(entry for entry in catalog if "chile" in entry.providers)
    if len(entries) != 1:
        raise ValueError("ChileSportsProvider currently requires exactly one configured competition")
    entry = entries[0]
    mapping = entry.providers["chile"]
    shared_session = session or requests.Session()
    timeout = int(environment.get("CHILE_SPORTS_HTTP_TIMEOUT_SECONDS", "15"))
    store = ChileSportsStore(environment.get("SPORTS_CONFIG_DB_PATH", ".data/sports-addon.db"))
    schedule_source = CampeonatoChilenoScheduleSource(
        environment.get(
            "CHILE_SPORTS_SCHEDULE_URL",
            "https://www.campeonatochileno.cl/competition/liga-de-primera/",
        ),
        session=shared_session,
        timeout=timeout,
        user_agent=environment.get(
            "CHILE_SPORTS_USER_AGENT",
            "RadioFlow-ChileSports/0.1 (+https://radioflow.media)",
        ),
    )
    announcement_source = AnfpAnnouncementSource(
        environment.get(
            "CHILE_SPORTS_ANFP_API_URL",
            "https://www.anfp.cl/wp-json/wp/v2/posts",
        ),
        session=shared_session,
        timeout=timeout,
        user_agent=environment.get(
            "CHILE_SPORTS_USER_AGENT",
            "RadioFlow-ChileSports/0.1 (+https://radioflow.media)",
        ),
    )
    sync_service = ChileSportsSyncService(
        store,
        schedule_source,
        announcement_source,
        competition_id=entry.id,
        competition_name=entry.name,
        country=entry.country,
        season=entry.current_season,
        external_competition_id=mapping.league_id,
        expected_team_count=int(environment.get("CHILE_SPORTS_EXPECTED_TEAM_COUNT", "16")),
        expected_match_count=int(environment.get("CHILE_SPORTS_EXPECTED_MATCH_COUNT", "240")),
        regular_interval=timedelta(
            hours=int(environment.get("CHILE_SPORTS_REGULAR_SYNC_HOURS", "24"))
        ),
        near_match_interval=timedelta(
            hours=int(environment.get("CHILE_SPORTS_NEAR_MATCH_SYNC_HOURS", "4"))
        ),
    )
    return ChileSportsProvider(store, sync_service)


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "chile": _create_chile,
    "thesportsdb": _create_thesportsdb,
}


def get_sports_provider(
    environment: Mapping[str, str] | None = None,
    *,
    catalog: tuple[CompetitionCatalogEntry, ...] | None = None,
    session: requests.Session | None = None,
    cache: SingleFlightTTLCache | None = None,
) -> SportsProvider:
    resolved_environment = environment if environment is not None else os.environ
    provider_name = resolved_environment.get("SPORTS_PROVIDER", "thesportsdb").strip().casefold()
    factory = PROVIDER_FACTORIES.get(provider_name)
    if not factory:
        raise ValueError(f"unsupported SPORTS_PROVIDER: {provider_name}")
    resolved_catalog = catalog or load_competition_catalog(resolved_environment.get("SPORTS_COMPETITIONS_FILE"))
    return factory(resolved_environment, resolved_catalog, session, cache)
