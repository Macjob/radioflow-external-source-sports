from unittest.mock import MagicMock, patch

from app.api_football_client import ApiFootballClient


def response(payload, headers=None):
    result = MagicMock()
    result.json.return_value = payload
    result.headers = headers or {}
    return result


@patch("app.api_football_client.requests.get")
def test_uses_only_official_get_header_and_caches_catalog_calls(get):
    get.return_value = response({"errors": [], "response": [{"league": {"id": 265}}]})
    client = ApiFootballClient("secret")

    first = client.get_leagues("Chile")
    second = client.get_leagues("Chile")

    assert first == second
    assert get.call_count == 1
    _, kwargs = get.call_args
    assert kwargs["headers"] == {"x-apisports-key": "secret"}
    assert kwargs["params"] == {"country": "Chile"}


@patch("app.api_football_client.requests.get")
def test_returns_no_rows_when_provider_reports_plan_errors(get):
    get.return_value = response({"errors": {"plan": "season unavailable"}, "response": []})
    assert ApiFootballClient("secret").get_teams(265, 2026) == []
