from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.addon_protocol import ADDON_ID, AddonEventEnvelope
from app.hosted_configuration import StoredConfiguration
from app.sports_provider import ScheduledMatch


def scheduled_matches_to_suggest_block_events(
    matches: list[ScheduledMatch],
    configuration: StoredConfiguration,
    duration_minutes: int = 120,
    schedule_timezone: str = "America/Santiago",
) -> list[AddonEventEnvelope]:
    try:
        target_timezone = ZoneInfo(schedule_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("SPORTS_SCHEDULE_TIMEZONE is invalid") from error

    selected_team_ids = {team["id"] for team in configuration.teams}
    selected_team_names = {team["id"]: team["name"] for team in configuration.teams}
    events: list[AddonEventEnvelope] = []
    seen_matches: set[str] = set()

    for match in matches:
        involved = selected_team_ids.intersection({match.home_team.id, match.away_team.id})
        if (
            match.id in seen_matches
            or match.status != "scheduled"
            or match.competition_id != configuration.competition["id"]
            or not involved
            or match.starts_at.tzinfo is None
        ):
            continue
        starts_at = match.starts_at.astimezone(timezone.utc)
        local_start = starts_at.astimezone(target_timezone)
        local_end = local_start + timedelta(minutes=duration_minutes)
        selected_names = [selected_team_names[team_id] for team_id in sorted(involved)]
        event_team = ", ".join(selected_names)
        title = f"{match.home_team.name} vs {match.away_team.name}"
        starts_at_iso = starts_at.isoformat().replace("+00:00", "Z")
        events.append(
            AddonEventEnvelope(
                id=f"suggest_block:sports:{match.id}:{starts_at_iso}",
                type="suggest_block",
                timestamp=starts_at,
                source=ADDON_ID,
                data={
                    "externalContentId": f"sports:{match.id}",
                    "suggestedDate": local_start.strftime("%Y-%m-%d"),
                    "suggestedStartTime": local_start.strftime("%H:%M"),
                    "suggestedEndTime": local_end.strftime("%H:%M"),
                    "title": f"Hoy juega {event_team}",
                    "description": f"{title} a las {local_start.strftime('%H:%M')}",
                    "contentKind": "metadata_only",
                    "contentMode": "reference_only",
                    "renderMode": "display_card",
                    "fallbackStrategy": "skip",
                    "conflictPolicy": "reject",
                    "metadata": {
                        "sport": "football",
                        "team": event_team,
                        "competition": configuration.competition["name"],
                        "eventType": "match.scheduled",
                        "source": "sports-addon",
                        "startsAt": starts_at_iso,
                    },
                },
            )
        )
        seen_matches.add(match.id)
    events.sort(key=lambda event: event.timestamp)
    return events
