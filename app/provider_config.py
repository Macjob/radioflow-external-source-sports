import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderCompetitionMapping:
    league_id: str
    league_name: str


@dataclass(frozen=True)
class CompetitionCatalogEntry:
    id: str
    name: str
    country: str
    current_season: str
    providers: dict[str, ProviderCompetitionMapping]


def load_competition_catalog(path: str | Path | None = None) -> tuple[CompetitionCatalogEntry, ...]:
    configured_path = path or os.getenv("SPORTS_COMPETITIONS_FILE", "config/sports_competitions.json")
    try:
        payload = json.loads(Path(configured_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("sports competition catalog is unavailable or invalid") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError("sports competition catalog must contain at least one competition")
    return tuple(_parse_entry(item) for item in payload)


def _parse_entry(item: Any) -> CompetitionCatalogEntry:
    if not isinstance(item, dict):
        raise ValueError("invalid sports competition catalog entry")
    providers = item.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("sports competition must define provider mappings")
    mappings: dict[str, ProviderCompetitionMapping] = {}
    for provider_name, raw in providers.items():
        if not isinstance(provider_name, str) or not isinstance(raw, dict):
            raise ValueError("invalid sports provider mapping")
        league_id = str(raw.get("leagueId", "")).strip()
        league_name = str(raw.get("leagueName", "")).strip()
        if not league_id or not league_name:
            raise ValueError("sports provider mapping requires leagueId and leagueName")
        mappings[provider_name] = ProviderCompetitionMapping(league_id, league_name)
    identifier = str(item.get("id", "")).strip()
    name = str(item.get("name", "")).strip()
    country = str(item.get("country", "")).strip()
    season = str(item.get("currentSeason", "")).strip()
    if not identifier or not name or not country or not season:
        raise ValueError("sports competition catalog entry is incomplete")
    return CompetitionCatalogEntry(identifier, name, country, season, mappings)
