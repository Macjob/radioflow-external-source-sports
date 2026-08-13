import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


@dataclass(frozen=True)
class BroadcastStation:
    id: str
    label: str
    url: str
    stream_url: str
    country: str


@dataclass(frozen=True)
class CompetitionBroadcastMapping:
    default_station_id: str | None
    team_station_ids: dict[str, str]


@dataclass(frozen=True)
class BroadcastResolution:
    station: BroadcastStation
    resolution: str


class BroadcastCatalog:
    def __init__(
        self,
        stations: dict[str, BroadcastStation],
        competitions: dict[str, CompetitionBroadcastMapping],
    ):
        self._stations = stations
        self._competitions = competitions

    def resolve(
        self,
        competition_id: str,
        preferred_team_ids: list[str] | tuple[str, ...],
    ) -> BroadcastResolution | None:
        mapping = self._competitions.get(competition_id)
        if not mapping:
            return None

        for team_id in preferred_team_ids:
            station_id = mapping.team_station_ids.get(team_id)
            if station_id:
                return BroadcastResolution(self._stations[station_id], "team_preference")

        if mapping.default_station_id:
            return BroadcastResolution(
                self._stations[mapping.default_station_id],
                "competition_default",
            )
        return None


def load_broadcast_catalog(path: str | Path | None = None) -> BroadcastCatalog:
    configured_path = path or os.getenv(
        "SPORTS_BROADCASTS_FILE",
        "config/sports_broadcasts.json",
    )
    try:
        payload = json.loads(Path(configured_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("sports broadcast catalog is unavailable or invalid") from error

    root = _mapping(payload, "sports broadcast catalog")
    stations_raw = _mapping(root.get("stations"), "sports broadcast stations")
    competitions_raw = _mapping(root.get("competitions"), "sports broadcast competitions")
    if not stations_raw or not competitions_raw:
        raise ValueError("sports broadcast catalog must define stations and competitions")

    stations = {
        station_id: _parse_station(station_id, raw)
        for station_id, raw in stations_raw.items()
    }
    competitions = {
        competition_id: _parse_competition(competition_id, raw, stations)
        for competition_id, raw in competitions_raw.items()
    }
    return BroadcastCatalog(stations, competitions)


def _parse_station(station_id: Any, raw: Any) -> BroadcastStation:
    identifier = _identifier(station_id, "station")
    station = _mapping(raw, f"station {identifier}")
    label = _string(station.get("label"), f"station {identifier} label", max_length=120)
    homepage_url = _https_url(station.get("url"), f"station {identifier} url")
    stream_url = _https_url(station.get("streamUrl"), f"station {identifier} streamUrl")
    country = _string(station.get("country"), f"station {identifier} country", max_length=2).upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError(f"station {identifier} country must be an ISO alpha-2 code")
    return BroadcastStation(identifier, label, homepage_url, stream_url, country)


def _parse_competition(
    competition_id: Any,
    raw: Any,
    stations: dict[str, BroadcastStation],
) -> CompetitionBroadcastMapping:
    identifier = _identifier(competition_id, "competition")
    mapping = _mapping(raw, f"competition {identifier}")
    default_station = mapping.get("defaultStation")
    if default_station is not None:
        default_station = _identifier(default_station, "station")
        _require_station(default_station, stations, identifier)

    teams_raw = mapping.get("teamStations", {})
    team_mapping = _mapping(teams_raw, f"competition {identifier} teamStations")
    team_station_ids: dict[str, str] = {}
    for team_id, station_id in team_mapping.items():
        normalized_team_id = _string(team_id, "team id", max_length=180)
        normalized_station_id = _identifier(station_id, "station")
        _require_station(normalized_station_id, stations, identifier)
        team_station_ids[normalized_team_id] = normalized_station_id

    if not default_station and not team_station_ids:
        raise ValueError(f"competition {identifier} must define a broadcast mapping")
    return CompetitionBroadcastMapping(default_station, team_station_ids)


def _require_station(
    station_id: str,
    stations: dict[str, BroadcastStation],
    competition_id: str,
) -> None:
    if station_id not in stations:
        raise ValueError(
            f"competition {competition_id} references unknown station {station_id}"
        )


def _https_url(value: Any, field: str) -> str:
    normalized = _string(value, field, max_length=2048)
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field} must be an HTTPS URL without embedded credentials")
    return normalized


def _identifier(value: Any, kind: str) -> str:
    normalized = _string(value, f"{kind} id", max_length=80)
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid {kind} id")
    return normalized


def _string(value: Any, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} is required")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"{field} is invalid")
    return normalized


def _mapping(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value
