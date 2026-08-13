import os
from collections.abc import Callable, Mapping

import requests

from app.provider_cache import SingleFlightTTLCache
from app.provider_config import CompetitionCatalogEntry, load_competition_catalog
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


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {"thesportsdb": _create_thesportsdb}


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
