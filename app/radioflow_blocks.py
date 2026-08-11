import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.config import Config
from app.models import (
    ExternalBlockAction,
    RadioflowExternalBlock,
    RadioflowExternalSuggestion,
    SportsEvent,
)

logger = logging.getLogger(__name__)


def to_radioflow_blocks(
    events: list[SportsEvent],
    config: Config,
) -> list[RadioflowExternalBlock]:
    blocks: list[RadioflowExternalBlock] = []
    for event in events:
        local_time = event.starts_at.strftime("%H:%M")
        team = event.team
        title = f"Hoy juega {team}"
        description = f"{event.title} a las {local_time}"

        radio = event.radio
        if radio:
            action = ExternalBlockAction(
                type="open_stream",
                label=f"Escuchar en {radio.label}",
                url=radio.url,
            )
        else:
            action = ExternalBlockAction(
                type="open_stream",
                label="Sin radio asignada",
                url="",
            )

        block = RadioflowExternalBlock(
            external_id=f"sports-{event.id}",
            title=title,
            description=description,
            start_time=event.starts_at.isoformat(),
            duration_minutes=config.default_match_duration_minutes,
            action=action,
            metadata={
                "sport": "football",
                "team": team,
                "source": event.source,
            },
        )
        blocks.append(block)

    logger.debug("Transformed %d events into %d radioflow blocks", len(events), len(blocks))
    return blocks


def to_radioflow_suggestions(
    events: list[SportsEvent],
    config: Config,
    source_key: str,
) -> list[RadioflowExternalSuggestion]:
    suggestions: list[RadioflowExternalSuggestion] = []
    timezone = ZoneInfo(config.timezone)

    for event in events:
        starts_at = event.starts_at.astimezone(timezone)
        ends_at = starts_at + timedelta(minutes=config.default_match_duration_minutes)
        local_time = starts_at.strftime("%H:%M")
        team = event.team
        metadata = {
            "sport": "football",
            "team": team,
            "source": event.source,
        }

        if event.radio:
            metadata["radioLabel"] = event.radio.label
            metadata["radioUrl"] = event.radio.url
            if event.radio.country:
                metadata["radioCountry"] = event.radio.country
            if event.radio.stream_url:
                metadata["stationName"] = event.radio.label
                metadata["streamUrl"] = event.radio.stream_url

        suggestion = RadioflowExternalSuggestion(
            source_key=source_key,
            external_content_id=f"sports-{event.id}",
            title=f"Hoy juega {team}",
            description=f"{event.title} a las {local_time}",
            suggested_date=starts_at.date().isoformat(),
            suggested_start_time=starts_at.strftime("%H:%M"),
            suggested_end_time=ends_at.strftime("%H:%M"),
            metadata=metadata,
        )
        suggestions.append(suggestion)

    logger.debug(
        "Transformed %d events into %d RadioFlow v0 suggestions",
        len(events),
        len(suggestions),
    )
    return suggestions
