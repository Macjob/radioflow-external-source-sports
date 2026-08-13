from copy import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

from app.chile_sports.models import SourceDocument
from app.chile_sports.sources import CampeonatoChilenoScheduleSource
from app.chile_sports.storage import ChileSportsStore
from app.chile_sports.sync import ChileSportsSyncService
from app.providers.chile import ChileSportsProvider
from app.sports_provider import (
    CompletedMatchOptions,
    ProviderInvalidResponseError,
    ProviderUnavailableError,
    ScheduledMatchOptions,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEDULE_URL = "https://www.campeonatochileno.cl/competition/liga-de-primera/"


class Response:
    def __init__(self, body: str = "", status_code: int = 200, headers: dict | None = None):
        self.text = body
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html; charset=UTF-8"}


class SequenceSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def parse(name: str = "campeonato_liga_primera_2026.html"):
    source = CampeonatoChilenoScheduleSource(SCHEDULE_URL)
    return source.parse(
        SourceDocument(fixture(name), datetime(2026, 8, 13, tzinfo=timezone.utc)),
        competition_id="chile-primera-division",
        competition_name="Primera División de Chile",
        country="Chile",
        expected_season="2026",
        external_competition_id="liga-de-primera",
    )


def service(store, session):
    source = CampeonatoChilenoScheduleSource(SCHEDULE_URL, session=session)
    return ChileSportsSyncService(
        store,
        source,
        None,
        competition_id="chile-primera-division",
        competition_name="Primera División de Chile",
        country="Chile",
        season="2026",
        external_competition_id="liga-de-primera",
        expected_team_count=1,
        expected_match_count=1,
    )


def test_parser_normalizes_teams_utc_results_suspension_and_tbd_time():
    snapshot = parse()

    assert snapshot.competition.name == "Primera División de Chile"
    assert len(snapshot.matches) == 5
    scheduled = next(match for match in snapshot.matches if match.external_id == "45009")
    assert scheduled.starts_at == datetime(2026, 8, 16, 21, 30, tzinfo=timezone.utc)
    assert scheduled.home_team.id == "chile-primera-division:colo-colo"
    assert scheduled.away_team.id == "chile-primera-division:o-higgins"
    assert scheduled.venue == "Estadio Monumental David Arellano"
    finished = next(match for match in snapshot.matches if match.external_id == "44979")
    assert (finished.status, finished.home_score, finished.away_score) == ("finished", 3, 1)
    tbd = next(match for match in snapshot.matches if match.external_id == "45020")
    assert tbd.starts_at is None
    assert tbd.time_confirmed is False
    assert tbd.home_team.name == "Universidad Católica"
    suspended = next(match for match in snapshot.matches if match.external_id == "45030")
    assert suspended.status == "suspended"


def test_sync_persists_data_and_reprograms_same_internal_match(tmp_path):
    initial = Response(
        fixture("campeonato_liga_primera_2026.html"),
        headers={"content-type": "text/html", "last-modified": "Thu, 13 Aug 2026 02:00:00 GMT"},
    )
    updated = Response(
        fixture("campeonato_liga_primera_2026_reprogrammed.html"),
        headers={"content-type": "text/html", "last-modified": "Thu, 13 Aug 2026 03:00:00 GMT"},
    )
    session = SequenceSession(initial, updated)
    store = ChileSportsStore(tmp_path / "sports-addon.db")
    sync = service(store, session)
    provider = ChileSportsProvider(store, sync)

    assert provider.sync_if_due(force=True) is True
    options = ScheduledMatchOptions(
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    before = next(match for match in provider.get_scheduled_matches("chile-primera-division", options)
                  if match.home_team.name == "Everton")
    assert before.starts_at == datetime(2026, 5, 23, 0, 0, tzinfo=timezone.utc)
    assert provider.sync_if_due(force=True) is True
    after_rows = provider.get_scheduled_matches("chile-primera-division", options)
    after = next(match for match in after_rows if match.home_team.name == "Everton")
    assert after.id == before.id
    assert after.starts_at == datetime(2026, 5, 22, 19, 0, tzinfo=timezone.utc)
    assert after.venue == "Estadio Elías Figueroa Brander"
    assert any(match.home_team.name == "Colo Colo" for match in after_rows)
    assert session.calls[1][1]["headers"]["If-Modified-Since"] == "Thu, 13 Aug 2026 02:00:00 GMT"

    results = provider.get_results(
        "chile-primera-division",
        CompletedMatchOptions(
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 1, tzinfo=timezone.utc),
        ),
    )
    assert len(results) == 1
    assert (results[0].home_score, results[0].away_score) == (3, 1)


def test_temporary_outage_and_changed_html_preserve_last_good_snapshot(tmp_path):
    session = SequenceSession(
        Response(fixture("campeonato_liga_primera_2026.html")),
        requests.ConnectionError("offline"),
        Response("<html><body>changed</body></html>"),
    )
    store = ChileSportsStore(tmp_path / "sports-addon.db")
    sync = service(store, session)
    provider = ChileSportsProvider(store, sync)
    provider.sync_if_due(force=True)
    original_ids = [match.id for match in store.get_scheduled_matches(
        "chile-primera-division",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )]

    with pytest.raises(ProviderUnavailableError):
        provider.sync_if_due(force=True)
    with pytest.raises(ProviderInvalidResponseError):
        provider.sync_if_due(force=True)

    assert [match.id for match in store.get_scheduled_matches(
        "chile-primera-division",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )] == original_ids
    assert store.sync_state("campeonatochileno")["last_success_at"] is not None
    assert store.sync_state("campeonatochileno")["last_error"]


def test_conditional_not_modified_keeps_snapshot(tmp_path):
    session = SequenceSession(
        Response(
            fixture("campeonato_liga_primera_2026.html"),
            headers={"content-type": "text/html", "last-modified": "Thu, 13 Aug 2026 02:00:00 GMT"},
        ),
        Response(status_code=304),
    )
    store = ChileSportsStore(tmp_path / "sports-addon.db")
    sync = service(store, session)
    sync.sync_if_due(force=True)
    assert sync.sync_if_due(force=True) is True
    assert store.has_data()


def test_empty_fixture_and_duplicate_internal_match_are_rejected():
    source = CampeonatoChilenoScheduleSource(SCHEDULE_URL)
    arguments = {
        "competition_id": "chile-primera-division",
        "competition_name": "Primera División de Chile",
        "country": "Chile",
        "expected_season": "2026",
        "external_competition_id": "liga-de-primera",
    }
    with pytest.raises(ProviderInvalidResponseError, match="empty document"):
        source.parse(
            SourceDocument("", datetime(2026, 8, 13, tzinfo=timezone.utc)),
            **arguments,
        )

    soup = BeautifulSoup(fixture("campeonato_liga_primera_2026.html"), "html.parser")
    first_match = soup.select_one(".anwp-fl-game")
    first_match.insert_after(copy(first_match))
    with pytest.raises(ProviderInvalidResponseError, match="duplicate matches"):
        source.parse(
            SourceDocument(str(soup), datetime(2026, 8, 13, tzinfo=timezone.utc)),
            **arguments,
        )


def test_store_releases_sqlite_file_after_each_operation(tmp_path):
    database_path = tmp_path / "sports-addon.db"
    store = ChileSportsStore(database_path)

    assert store.has_data() is False
    database_path.unlink()
    assert not database_path.exists()
