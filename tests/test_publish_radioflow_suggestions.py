from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.config import Config
from app.models import RadioflowExternalSuggestion, RadioInfo, SportsEvent
from app.publish_radioflow_suggestions import main
from app.radioflow_publisher import PublishResult

REQUIRED_ENV = {
    "FOOTBALL_DATA_API_KEY": "football-key",
    "RADIOFLOW_BASE_URL": "http://radioflow.local",
    "RADIOFLOW_SOURCE_KEY": "sports-test",
    "RADIOFLOW_SOURCE_TOKEN": "rf_ext_token",
}


def _config() -> Config:
    return Config(
        timezone="America/Santiago",
        notification_window_minutes=30,
        default_match_duration_minutes=120,
        teams=["Colo-Colo"],
        team_mapping={"Colo-Colo": ["Colo-Colo"]},
        radios={"Colo-Colo": RadioInfo(label="Test Radio", url="https://example.com")},
    )


def _event(team: str = "Colo-Colo") -> SportsEvent:
    return SportsEvent(
        id=f"match-{team}",
        title=f"{team} vs Other Team",
        team=team,
        starts_at=datetime(2026, 6, 11, 19, 30, tzinfo=timezone.utc),
        timezone="America/Santiago",
        radio=RadioInfo(label="Test Radio", url="https://example.com"),
    )


def _suggestion(title: str) -> RadioflowExternalSuggestion:
    return RadioflowExternalSuggestion(
        source_key="sports-test",
        external_content_id=f"sports-{title}",
        title=title,
        description=f"{title} description",
        suggested_date="2026-06-11",
        suggested_start_time="19:30",
        suggested_end_time="21:30",
        metadata={"team": title},
    )


def _patch_common(return_events=None):
    stack = pytest.MonkeyPatch.context()
    monkeypatch = stack.__enter__()
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", REQUIRED_ENV["FOOTBALL_DATA_API_KEY"])
    monkeypatch.setenv("RADIOFLOW_BASE_URL", REQUIRED_ENV["RADIOFLOW_BASE_URL"])
    monkeypatch.setenv("RADIOFLOW_SOURCE_KEY", REQUIRED_ENV["RADIOFLOW_SOURCE_KEY"])
    monkeypatch.setenv("RADIOFLOW_SOURCE_TOKEN", REQUIRED_ENV["RADIOFLOW_SOURCE_TOKEN"])
    patches = [
        patch("app.publish_radioflow_suggestions.load_dotenv"),
        patch("app.publish_radioflow_suggestions.load_config", return_value=_config()),
        patch("app.publish_radioflow_suggestions.FootballDataClient"),
        patch("app.publish_radioflow_suggestions.get_relevant_matches", return_value=return_events if return_events is not None else [_event()]),
    ]
    started = [p.start() for p in patches]
    return stack, patches, started


def _cleanup(stack, patches):
    for patched in reversed(patches):
        patched.stop()
    stack.__exit__(None, None, None)


class TestPublishRadioflowSuggestionsCli:
    def test_dry_run_does_not_call_publisher_and_prints_camel_case_payloads(self, capsys):
        stack, patches, _ = _patch_common()
        try:
            with patch("app.publish_radioflow_suggestions.RadioflowPublisher") as publisher_cls:
                exit_code = main(["--dry-run"])
        finally:
            _cleanup(stack, patches)

        output = capsys.readouterr().out
        assert exit_code == 0
        publisher_cls.assert_not_called()
        assert '"sourceKey": "sports-test"' in output
        assert '"externalContentId": "sports-match-Colo-Colo"' in output
        assert "source_key" not in output
        assert "Dry run: true" in output

    def test_missing_required_env_exits_with_clear_error(self, capsys, monkeypatch):
        for key in REQUIRED_ENV:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "football-key")

        with patch("app.publish_radioflow_suggestions.load_dotenv"):
            exit_code = main([])

        output = capsys.readouterr().out
        assert exit_code == 1
        assert "Missing required environment variables" in output
        assert "RADIOFLOW_BASE_URL" in output
        assert "RADIOFLOW_SOURCE_KEY" in output
        assert "RADIOFLOW_SOURCE_TOKEN" in output

    def test_country_is_passed_to_match_lookup(self):
        stack, patches, started = _patch_common()
        get_relevant_matches = started[3]
        try:
            with patch("app.publish_radioflow_suggestions.RadioflowPublisher") as publisher_cls:
                publisher = publisher_cls.return_value
                publisher.publish_suggestion.return_value = PublishResult(ok=True, status="created", http_status=201, suggestion_id="sug-1")
                exit_code = main(["--country", "Chile"])
        finally:
            _cleanup(stack, patches)

        assert exit_code == 0
        assert get_relevant_matches.call_args.kwargs["country"] == "Chile"

    def test_mixed_results_are_counted_in_summary(self, capsys):
        stack, patches, _ = _patch_common(return_events=[_event("Colo-Colo"), _event("U. de Chile"), _event("Universidad Catolica")])
        suggestions = [
            _suggestion("Hoy juega Colo-Colo"),
            _suggestion("Hoy juega U. de Chile"),
            _suggestion("Hoy juega Universidad Catolica"),
        ]
        try:
            with patch("app.publish_radioflow_suggestions.to_radioflow_suggestions", return_value=suggestions):
                with patch("app.publish_radioflow_suggestions.RadioflowPublisher") as publisher_cls:
                    publisher = publisher_cls.return_value
                    publisher.publish_suggestion.side_effect = [
                        PublishResult(ok=True, status="created", http_status=201, suggestion_id="sug-1"),
                        PublishResult(ok=True, status="deduplicated", http_status=200, suggestion_id="sug-2"),
                        PublishResult(ok=False, status="failed", http_status=401, code="invalid_token", message="Invalid external source token."),
                    ]
                    exit_code = main([])
        finally:
            _cleanup(stack, patches)

        output = capsys.readouterr().out
        assert exit_code == 1
        assert "[created] Hoy juega Colo-Colo - suggestionId=sug-1" in output
        assert "[deduplicated] Hoy juega U. de Chile - suggestionId=sug-2" in output
        assert "[failed] Hoy juega Universidad Catolica - 401 invalid_token: Invalid external source token." in output
        assert "- found: 3" in output
        assert "- prepared: 3" in output
        assert "- created: 1" in output
        assert "- deduplicated: 1" in output
        assert "- failed: 1" in output
