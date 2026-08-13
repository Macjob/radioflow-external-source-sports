import json

import pytest

from app.broadcast_catalog import load_broadcast_catalog


def _catalog_payload() -> dict:
    return {
        "stations": {
            "station-a": {
                "label": "Station A",
                "url": "https://radio.example.com/",
                "streamUrl": "https://stream.example.com/live.mp3",
                "country": "cl",
            },
            "station-b": {
                "label": "Station B",
                "url": "https://other.example.com/",
                "streamUrl": "https://stream.example.com/other.aac",
                "country": "CL",
            },
        },
        "competitions": {
            "competition-a": {
                "defaultStation": "station-a",
                "teamStations": {"competition-a:team-b": "station-b"},
            }
        },
    }


def _write_catalog(tmp_path, payload: dict):
    path = tmp_path / "broadcasts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_resolves_team_preference_before_competition_default(tmp_path):
    catalog = load_broadcast_catalog(_write_catalog(tmp_path, _catalog_payload()))

    resolved = catalog.resolve("competition-a", ["competition-a:team-b"])

    assert resolved is not None
    assert resolved.resolution == "team_preference"
    assert resolved.station.id == "station-b"
    assert resolved.station.country == "CL"


def test_uses_competition_default_for_an_unmapped_team(tmp_path):
    catalog = load_broadcast_catalog(_write_catalog(tmp_path, _catalog_payload()))

    resolved = catalog.resolve("competition-a", ["competition-a:team-c"])

    assert resolved is not None
    assert resolved.resolution == "competition_default"
    assert resolved.station.id == "station-a"
    assert catalog.resolve("unknown-competition", []) is None


def test_rejects_unknown_station_references(tmp_path):
    payload = _catalog_payload()
    payload["competitions"]["competition-a"]["defaultStation"] = "missing"

    with pytest.raises(ValueError, match="references unknown station"):
        load_broadcast_catalog(_write_catalog(tmp_path, payload))


@pytest.mark.parametrize(
    "url",
    [
        "http://stream.example.com/live.mp3",
        "https://user:secret@stream.example.com/live.mp3",
        "javascript:alert(1)",
    ],
)
def test_rejects_unsafe_stream_urls(tmp_path, url):
    payload = _catalog_payload()
    payload["stations"]["station-a"]["streamUrl"] = url

    with pytest.raises(ValueError, match="HTTPS URL without embedded credentials"):
        load_broadcast_catalog(_write_catalog(tmp_path, payload))
