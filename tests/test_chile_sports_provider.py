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


def fallback_html(kickoff: str = "2026-08-16T18:30:00-04:00") -> str:
    return f"""
    <html><body>
      <div class="anwp-fl-game match-card game-status-0" data-anwp-match="45009" data-fl-game-datetime="{kickoff}">
        <div class="match-card__header-item">Liga de Primera</div>
        <div class="match-card__header-item">Fecha 19</div>
        <div class="match-card__club-title">Colo Colo</div>
        <span class="anwp-fl-game__scores-home">-</span>
        <span class="anwp-fl-game__scores-away">-</span>
        <div class="match-card__club-title">O’Higgins</div>
        <span class="match__time-formatted">18:30</span>
        <a class="anwp-link-cover" href="https://www.campeonatochileno.cl/match/colo-colo-ohiggins-2026-08-16/"></a>
      </div>
      <div class="anwp-fl-game match-card game-status-0" data-anwp-match="other" data-fl-game-datetime="2026-08-16T20:00:00-04:00">
        <div class="match-card__header-item">Liga de Ascenso</div>
        <div class="match-card__header-item">Fecha 19</div>
        <div class="match-card__club-title">Otro Local</div>
        <div class="match-card__club-title">Otro Visitante</div>
        <span class="match__time-formatted">20:00</span>
        <a class="anwp-link-cover" href="https://www.campeonatochileno.cl/match/otro/"></a>
      </div>
    </body></html>
    """


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


def test_schedule_403_without_fallback_remains_an_error():
    source = CampeonatoChilenoScheduleSource(SCHEDULE_URL, session=SequenceSession(Response(status_code=403)))

    with pytest.raises(ProviderInvalidResponseError, match="HTTP 403"):
        source.fetch()


def test_schedule_403_uses_official_partial_fallback_without_reusing_conditional_header():
    session = SequenceSession(
        Response(status_code=403),
        Response(
            fallback_html(),
            headers={"content-type": "text/html", "last-modified": "Fri, 11 Sep 2026 19:51:52 GMT"},
        ),
    )
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
        session=session,
    )

    document = source.fetch("Thu, 02 Sep 2026 17:04:52 GMT")

    assert document.partial is True
    assert document.last_modified is None
    assert session.calls[0][0] == SCHEDULE_URL
    assert session.calls[0][1]["headers"]["If-Modified-Since"] == "Thu, 02 Sep 2026 17:04:52 GMT"
    assert session.calls[1][0] == "https://www.campeonatochileno.cl/pagina-2026/"
    assert "If-Modified-Since" not in session.calls[1][1]["headers"]


def test_schedule_fallback_304_is_not_treated_as_primary_not_modified():
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
        session=SequenceSession(Response(status_code=403), Response(status_code=304)),
    )

    with pytest.raises(ProviderInvalidResponseError, match="fallback returned HTTP 304"):
        source.fetch("Thu, 02 Sep 2026 17:04:52 GMT")


def test_schedule_fallback_failure_preserves_provider_error_category():
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
        session=SequenceSession(Response(status_code=403), requests.Timeout("slow")),
    )

    with pytest.raises(ProviderUnavailableError, match="fallback is unavailable"):
        source.fetch()


def test_primary_success_does_not_touch_fallback():
    session = SequenceSession(Response(fixture("campeonato_liga_primera_2026.html")))
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
        session=session,
    )

    document = source.fetch()

    assert document.partial is False
    assert len(session.calls) == 1
    assert session.calls[0][0] == SCHEDULE_URL


def test_partial_fallback_filters_competition_and_preserves_stable_match_identity():
    full = parse()
    original = next(match for match in full.matches if match.external_id == "45009")
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
    )
    partial = source.parse(
        SourceDocument(
            fallback_html(),
            datetime(2026, 9, 11, tzinfo=timezone.utc),
            partial=True,
        ),
        competition_id="chile-primera-division",
        competition_name="Primera División de Chile",
        country="Chile",
        expected_season="2026",
        external_competition_id="liga-de-primera",
    )

    assert len(partial.matches) == 1
    refreshed = partial.matches[0]
    assert refreshed.external_id == "45009"
    assert refreshed.id == original.id
    assert refreshed.starts_at == datetime(2026, 8, 16, 22, 30, tzinfo=timezone.utc)
    assert refreshed.home_team.name == "Colo Colo"
    assert refreshed.away_team.name == "O'Higgins"


def test_partial_fallback_refreshes_existing_match_without_dropping_snapshot_details(tmp_path):
    store = ChileSportsStore(tmp_path / "sports-addon.db")
    full = parse()
    store.store_snapshot(
        full,
        source="campeonatochileno",
        fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        last_modified="Wed, 02 Sep 2026 17:04:52 GMT",
    )
    session = SequenceSession(Response(status_code=403), Response(fallback_html()))
    source = CampeonatoChilenoScheduleSource(
        SCHEDULE_URL,
        fallback_url="https://www.campeonatochileno.cl/pagina-2026/",
        session=session,
    )
    sync = ChileSportsSyncService(
        store,
        source,
        None,
        competition_id="chile-primera-division",
        competition_name="Primera División de Chile",
        country="Chile",
        season="2026",
        external_competition_id="liga-de-primera",
        expected_team_count=16,
        expected_match_count=240,
    )

    assert sync.sync_if_due(force=True) is True
    rows = store.get_scheduled_matches(
        "chile-primera-division",
        datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    refreshed = next(match for match in rows if match.home_team.name == "Colo Colo")

    assert any(match.home_team.name == "Everton" for match in rows)
    assert refreshed.starts_at == datetime(2026, 8, 16, 22, 30, tzinfo=timezone.utc)
    assert refreshed.venue == "Estadio Monumental David Arellano"
    state = store.sync_state("campeonatochileno")
    assert state["last_success_at"] is not None
    assert state["last_error"] is None
    assert state["last_modified"] is None


def test_store_releases_sqlite_file_after_each_operation(tmp_path):
    database_path = tmp_path / "sports-addon.db"
    store = ChileSportsStore(database_path)

    assert store.has_data() is False
    database_path.unlink()
    assert not database_path.exists()
