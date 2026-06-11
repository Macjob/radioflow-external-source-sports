import json
import logging
from pathlib import Path

from pydantic import BaseModel

from app.models import CountryConfig, RadioInfo

logger = logging.getLogger(__name__)


class Config(BaseModel):
    timezone: str = "America/Santiago"
    notification_window_minutes: int = 30
    default_match_duration_minutes: int = 120
    teams: list[str] = []
    team_mapping: dict[str, list[str]] = {}
    radios: dict[str, RadioInfo] = {}
    countries: dict[str, CountryConfig] = {}


def find_config_file() -> Path:
    candidates = [
        Path.cwd() / "config.json",
        Path(__file__).resolve().parent.parent / "config.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "config.json not found. Create it from config.example.json in the project root."
    )


def _parse_radios(radios_raw: dict) -> dict[str, RadioInfo]:
    return {team: RadioInfo(**info) for team, info in radios_raw.items()}


def _parse_country(name: str, raw: dict) -> CountryConfig:
    return CountryConfig(
        teams=raw["teams"],
        team_mapping=raw.get("team_mapping", {}),
        radios=_parse_radios(raw.get("radios", {})),
        default_radio=RadioInfo(**raw["default_radio"]) if "default_radio" in raw else None,
    )


def load_config() -> Config:
    path = find_config_file()
    logger.info("Loading config from %s", path)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        logger.critical("Invalid JSON in config.json: %s", e)
        raise

    common = dict(
        timezone=raw.get("timezone", "America/Santiago"),
        notification_window_minutes=raw.get("notification_window_minutes", 30),
        default_match_duration_minutes=raw.get("default_match_duration_minutes", 120),
    )

    if "countries" in raw:
        countries = {name: _parse_country(name, c) for name, c in raw["countries"].items()}
        return Config(countries=countries, **common)

    teams = raw.get("teams", [])
    team_mapping = raw.get("team_mapping", {})
    radios = _parse_radios(raw.get("radios", {}))
    return Config(teams=teams, team_mapping=team_mapping, radios=radios, **common)
