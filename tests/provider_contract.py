from dataclasses import asdict
from datetime import datetime, timezone

from app.sports_provider import ScheduledMatchOptions, SportsProvider


def assert_sports_provider_contract(provider: SportsProvider, now: datetime):
    competitions = provider.get_competitions()
    assert competitions
    assert all(isinstance(competition.id, str) and competition.id for competition in competitions)
    assert all("idLeague" not in asdict(competition) for competition in competitions)

    competition = competitions[0]
    teams = provider.get_teams(competition.id)
    assert teams
    assert provider.get_teams(competition.id) == teams
    assert all(isinstance(team.id, str) and team.id for team in teams)
    assert all("idTeam" not in asdict(team) for team in teams)

    matches = provider.get_scheduled_matches(
        competition.id,
        ScheduledMatchOptions(starts_after=now, starts_before=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    )
    assert matches
    assert provider.get_scheduled_matches(
        competition.id,
        ScheduledMatchOptions(starts_after=now, starts_before=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    ) == matches
    assert all(match.status == "scheduled" for match in matches)
    assert all(match.starts_at.tzinfo is timezone.utc for match in matches)
    assert all(match.starts_at >= now for match in matches)
    assert all("idEvent" not in asdict(match) and "strTimestamp" not in asdict(match) for match in matches)
