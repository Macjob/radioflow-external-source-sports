import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config import Config
from app.models import CountryConfig, RadioInfo


def today_at_utc(timezone_name: str = "America/Santiago", hour: int = 19, minute: int = 30) -> str:
    local_now = datetime.now(ZoneInfo(timezone_name))
    local_match = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_match.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SAMPLE_CONFIG_FLAT: dict[str, Any] = {
    "timezone": "America/Santiago",
    "notification_window_minutes": 30,
    "default_match_duration_minutes": 120,
    "teams": ["Colo-Colo", "U. de Chile", "Universidad Católica"],
    "team_mapping": {
        "Colo-Colo": ["Colo-Colo", "CD Colo-Colo"],
        "U. de Chile": ["U. de Chile", "Universidad de Chile", "Club Universidad de Chile"],
        "Universidad Católica": ["Universidad Católica", "CD Universidad Católica"],
    },
    "radios": {
        "Colo-Colo": {
            "label": "Cooperativa 93.3 FM",
            "url": "https://www.cooperativa.cl",
            "streamUrl": "https://stream.example.com/cooperativa.aac",
            "country": "CL",
        },
        "U. de Chile": {"label": "ADN Radio 91.7 FM", "url": "https://www.adnradio.cl"},
        "Universidad Católica": {
            "label": "Radio Agricultura",
            "url": "https://www.radioagricultura.cl",
        },
    },
}

SAMPLE_CONFIG_COUNTRIES: dict[str, Any] = {
    "timezone": "America/Santiago",
    "notification_window_minutes": 30,
    "default_match_duration_minutes": 120,
    "countries": {
        "Chile": {
            "teams": ["Colo-Colo", "U. de Chile"],
            "team_mapping": {
                "Colo-Colo": ["Colo-Colo", "CD Colo-Colo"],
                "U. de Chile": ["U. de Chile", "Universidad de Chile"],
            },
            "radios": {
                "Colo-Colo": {"label": "Cooperativa 93.3 FM", "url": "https://www.cooperativa.cl", "country": "CL"},
                "U. de Chile": {"label": "ADN Radio 91.7 FM", "url": "https://www.adnradio.cl"},
            },
            "default_radio": {"label": "Radio Cooperativa", "url": "https://www.cooperativa.cl"},
        },
        "México": {
            "teams": ["México"],
            "team_mapping": {"México": ["Mexico", "México"]},
            "radios": {
                "México": {"label": "W Radio 96.9 FM", "url": "https://www.wradio.com.mx"},
            },
        },
    },
}


def _build_country_config(name: str, raw: dict) -> CountryConfig:
    radios = {team: RadioInfo(**info) for team, info in raw.get("radios", {}).items()}
    return CountryConfig(
        teams=raw["teams"],
        team_mapping=raw.get("team_mapping", {}),
        radios=radios,
        default_radio=RadioInfo(**raw["default_radio"]) if "default_radio" in raw else None,
    )


@pytest.fixture
def sample_config() -> Config:
    return Config(
        timezone=SAMPLE_CONFIG_FLAT["timezone"],
        notification_window_minutes=SAMPLE_CONFIG_FLAT["notification_window_minutes"],
        default_match_duration_minutes=SAMPLE_CONFIG_FLAT["default_match_duration_minutes"],
        teams=SAMPLE_CONFIG_FLAT["teams"],
        team_mapping=SAMPLE_CONFIG_FLAT["team_mapping"],
        radios={name: RadioInfo(**info) for name, info in SAMPLE_CONFIG_FLAT["radios"].items()},
    )


@pytest.fixture
def sample_config_countries() -> Config:
    countries = {
        name: _build_country_config(name, c)
        for name, c in SAMPLE_CONFIG_COUNTRIES["countries"].items()
    }
    return Config(
        timezone=SAMPLE_CONFIG_COUNTRIES["timezone"],
        notification_window_minutes=SAMPLE_CONFIG_COUNTRIES["notification_window_minutes"],
        default_match_duration_minutes=SAMPLE_CONFIG_COUNTRIES["default_match_duration_minutes"],
        countries=countries,
    )


@pytest.fixture
def sample_config_dict() -> dict[str, Any]:
    return SAMPLE_CONFIG_FLAT


@pytest.fixture
def temp_config_file(sample_config_dict: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> str:
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample_config_dict, f)
    monkeypatch.setattr("app.config.find_config_file", lambda: Path(path))
    yield path


@pytest.fixture
def sample_match() -> dict[str, Any]:
    return {
        "id": 123456,
        "utcDate": today_at_utc(),
        "status": "SCHEDULED",
        "homeTeam": {"id": 1, "name": "Colo-Colo"},
        "awayTeam": {"id": 2, "name": "Universidad Católica"},
        "competition": {"id": 2024, "name": "Primera División"},
    }


@pytest.fixture
def sample_matches(sample_match: dict[str, Any]) -> list:
    return {
        "matches": [
            sample_match,
            {
                "id": 789012,
                "utcDate": today_at_utc(hour=22, minute=0),
                "status": "SCHEDULED",
                "homeTeam": {"id": 3, "name": "CD Universidad Católica"},
                "awayTeam": {"id": 4, "name": "Otro Equipo"},
                "competition": {"id": 2024, "name": "Primera División"},
            },
        ]
    }
