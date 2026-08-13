import pytest

from app.provider_config import CompetitionCatalogEntry, ProviderCompetitionMapping
from app.provider_registry import get_sports_provider
from app.providers.thesportsdb import TheSportsDBProvider

CATALOG = (
    CompetitionCatalogEntry(
        id="chile-primera-division",
        name="Primera División de Chile",
        country="Chile",
        current_season="2026",
        providers={"thesportsdb": ProviderCompetitionMapping("4627", "Chile Primera Division")},
    ),
)


def test_registry_selects_configured_provider_once():
    provider = get_sports_provider(
        {"SPORTS_PROVIDER": "thesportsdb", "THESPORTSDB_API_KEY": "123"},
        catalog=CATALOG,
    )
    assert isinstance(provider, TheSportsDBProvider)
    assert provider.name == "thesportsdb"


def test_registry_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unsupported SPORTS_PROVIDER"):
        get_sports_provider({"SPORTS_PROVIDER": "unknown"}, catalog=CATALOG)
