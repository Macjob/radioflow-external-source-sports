import logging
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from app.config import Config
from app.football_client import FootballDataClient
from app.models import RadioInfo, SportsEvent

logger = logging.getLogger(__name__)


def _match_team(
    team_name: str,
    mapping: dict[str, list[str]],
) -> str | None:
    team_lower = team_name.lower()
    for config_team, aliases in mapping.items():
        for alias in aliases:
            if alias.lower() in team_lower:
                return config_team
    return None


def _extract_team_info(
    match: dict,
    teams: list[str],
    mapping: dict[str, list[str]],
    radios: dict[str, RadioInfo],
) -> list[tuple[str, str, RadioInfo | None]]:
    home_name = (match.get("homeTeam") or {}).get("name", "")
    away_name = (match.get("awayTeam") or {}).get("name", "")
    results: list[tuple[str, str, RadioInfo | None]] = []
    for team_name, _label in [(home_name, "home"), (away_name, "away")]:
        matched_key = _match_team(team_name, mapping)
        if matched_key and matched_key in teams:
            radio = radios.get(matched_key)
            if radio is None:
                logger.warning("No radio configured for team '%s'", matched_key)
            results.append((matched_key, team_name, radio))
    return results


def get_relevant_matches(
    config: Config,
    client: FootballDataClient,
    country: str | None = None,
) -> list[SportsEvent]:
    raw_matches = client.get_today_matches()
    if not raw_matches:
        logger.info("No matches returned from API")
        return []

    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    events: list[SportsEvent] = []

    if country and country in config.countries:
        cc = config.countries[country]
        teams, mapping, radios, default_radio = cc.teams, cc.team_mapping, cc.radios, cc.default_radio
    else:
        teams, mapping, radios = config.teams, config.team_mapping, config.radios
        default_radio = None

    for match in raw_matches:
        utc_date_str = match.get("utcDate")
        if not utc_date_str:
            continue

        try:
            utc_dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError) as e:
            logger.warning("Failed to parse date '%s': %s", utc_date_str, e)
            continue

        local_dt = utc_dt.astimezone(tz)
        match_day = local_dt.strftime("%Y-%m-%d")
        if match_day != today_str:
            continue

        home_name = (match.get("homeTeam") or {}).get("name", "")
        away_name = (match.get("awayTeam") or {}).get("name", "")
        match_id = match.get("id")
        if match_id is None:
            continue
        title = f"{home_name} vs {away_name}"

        team_infos = _extract_team_info(match, teams, mapping, radios)

        if team_infos:
            for matched_key, _original_name, radio in team_infos:
                event = SportsEvent(
                    id=f"match-{match_id}",
                    title=title,
                    team=matched_key,
                    starts_at=local_dt,
                    timezone=config.timezone,
                    radio=radio,
                )
                events.append(event)
        elif default_radio:
            event = SportsEvent(
                id=f"match-{match_id}",
                title=title,
                team="Internacional",
                starts_at=local_dt,
                timezone=config.timezone,
                radio=default_radio,
            )
            events.append(event)

    events.sort(key=lambda e: e.starts_at)
    logger.info("Found %d relevant events for today", len(events))
    return events
