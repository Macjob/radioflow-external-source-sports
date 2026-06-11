import logging

from app.config import Config
from app.models import (
    ExternalBlockAction,
    RadioflowExternalBlock,
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
