import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from app.provider_config import load_competition_catalog
from app.providers.thesportsdb import TheSportsDBProvider
from app.sports_provider import (
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderUnauthorizedError,
    ProviderUnavailableError,
    ScheduledMatchOptions,
)
from tests.provider_contract import assert_sports_provider_contract

FIXTURES = Path(__file__).parent / "fixtures"


def payload(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response(body: dict | None = None, status_code: int = 200):
    result = MagicMock()
    result.status_code = status_code
    result.json.return_value = body
    return result


def provider_with_payloads(*responses):
    session = MagicMock()
    session.get.side_effect = responses
    provider = TheSportsDBProvider("123", load_competition_catalog(), session=session)
    return provider, session


def test_thesportsdb_implements_reusable_provider_contract_and_utc_normalization():
    provider, _ = provider_with_payloads(
        response(payload("thesportsdb_teams_4627.json")),
        response(payload("thesportsdb_events_4627_2026.json")),
        response(payload("thesportsdb_events_4627_2026.json")),
    )
    assert_sports_provider_contract(provider, datetime(2026, 8, 13, tzinfo=timezone.utc))


def test_catalog_and_season_queries_are_cached_by_competition_not_installation():
    provider, session = provider_with_payloads(
        response(payload("thesportsdb_teams_4627.json")),
        response(payload("thesportsdb_events_4627_2026.json")),
        response(payload("thesportsdb_events_4627_2026.json")),
    )
    provider.get_teams("chile-primera-division")
    provider.get_teams("chile-primera-division")
    options = ScheduledMatchOptions(
        datetime(2026, 8, 13, tzinfo=timezone.utc),
        datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    provider.get_scheduled_matches("chile-primera-division", options)
    provider.get_scheduled_matches("chile-primera-division", options)
    assert session.get.call_count == 3
    first_url = session.get.call_args_list[0].args[0]
    second_url = session.get.call_args_list[1].args[0]
    third_url = session.get.call_args_list[2].args[0]
    assert first_url.endswith("/search_all_teams.php")
    assert second_url.endswith("/eventsseason.php")
    assert third_url.endswith("/eventsnextleague.php")
    assert session.get.call_args_list[0].kwargs["params"] == {"l": "Chile_Primera_Division"}
    assert session.get.call_args_list[1].kwargs["params"] == {"id": "4627", "s": "2026"}


def test_empty_provider_collections_are_supported():
    provider, _ = provider_with_payloads(
        response({"teams": None}),
        response({"events": None}),
        response({"events": None}),
    )
    assert provider.get_teams("chile-primera-division") == []
    assert provider.get_scheduled_matches(
        "chile-primera-division",
        ScheduledMatchOptions(
            datetime(2026, 8, 13, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
        ),
    ) == []


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, ProviderUnauthorizedError),
        (403, ProviderUnauthorizedError),
        (429, ProviderRateLimitedError),
        (503, ProviderUnavailableError),
        (400, ProviderInvalidResponseError),
    ],
)
def test_http_failures_are_normalized(status_code, expected):
    provider, _ = provider_with_payloads(response(status_code=status_code))
    with pytest.raises(expected):
        provider.get_teams("chile-primera-division")


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_network_failures_are_normalized(error):
    provider, _ = provider_with_payloads(error)
    with pytest.raises(ProviderUnavailableError):
        provider.get_teams("chile-primera-division")


def test_conflicting_or_ambiguous_time_is_rejected():
    provider, _ = provider_with_payloads(
        response({"events": [{
            "idEvent": "1",
            "strHomeTeam": "A",
            "strAwayTeam": "B",
            "dateEvent": "2026-08-14",
            "strTime": "20:00:00",
            "strTimestamp": "2026-08-14T21:00:00Z",
            "strStatus": "NS",
            "strPostponed": "no",
        }]}),
        response({"events": None}),
    )
    with pytest.raises(ProviderInvalidResponseError, match="conflicting"):
        provider.get_scheduled_matches(
            "chile-primera-division",
            ScheduledMatchOptions(
                datetime(2026, 8, 13, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            ),
        )
