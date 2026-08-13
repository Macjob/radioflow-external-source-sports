from datetime import datetime, timedelta
from typing import Any

from app.addon_protocol import ADDON_ID, AddonEventEnvelope
from app.hosted_configuration import StoredConfiguration


def fixtures_to_suggest_block_events(
    fixtures: list[dict[str, Any]],
    configuration: StoredConfiguration,
    duration_minutes: int = 120,
) -> list[AddonEventEnvelope]:
    selected_team_ids = {team["id"] for team in configuration.teams}
    selected_team_names = {team["id"]: team["name"] for team in configuration.teams}
    events: list[AddonEventEnvelope] = []
    seen_fixtures: set[int] = set()

    for row in fixtures:
        fixture = row.get("fixture") or {}
        fixture_id = fixture.get("id")
        fixture_date = fixture.get("date")
        status = (fixture.get("status") or {}).get("short")
        league = row.get("league") or {}
        teams = row.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        involved = selected_team_ids.intersection({home.get("id"), away.get("id")})
        if (
            not isinstance(fixture_id, int)
            or fixture_id in seen_fixtures
            or not isinstance(fixture_date, str)
            or status not in {"NS", "TBD"}
            or league.get("id") != configuration.competition["id"]
            or not involved
        ):
            continue
        try:
            starts_at = datetime.fromisoformat(fixture_date.replace("Z", "+00:00"))
        except ValueError:
            continue
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        selected_names = [selected_team_names[team_id] for team_id in sorted(involved)]
        title = f"{home.get('name', 'Home')} vs {away.get('name', 'Away')}"
        event_team = ", ".join(selected_names)
        events.append(
            AddonEventEnvelope(
                id=f"suggest_block:api-football:{fixture_id}:{starts_at.isoformat()}",
                type="suggest_block",
                timestamp=starts_at,
                source=ADDON_ID,
                data={
                    "externalContentId": f"api-football:{fixture_id}",
                    "suggestedDate": starts_at.strftime("%Y-%m-%d"),
                    "suggestedStartTime": starts_at.strftime("%H:%M"),
                    "suggestedEndTime": ends_at.strftime("%H:%M"),
                    "title": f"Hoy juega {event_team}",
                    "description": f"{title} a las {starts_at.strftime('%H:%M')}",
                    "contentKind": "metadata_only",
                    "contentMode": "reference_only",
                    "renderMode": "display_card",
                    "fallbackStrategy": "skip",
                    "conflictPolicy": "reject",
                    "metadata": {
                        "sport": "football",
                        "team": event_team,
                        "competition": str(league.get("name") or configuration.competition["name"]),
                        "eventType": "match.scheduled",
                        "source": "api-football.com",
                    },
                },
            )
        )
        seen_fixtures.add(fixture_id)
    events.sort(key=lambda event: event.timestamp)
    return events
