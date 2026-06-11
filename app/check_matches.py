import logging
import sys
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import os

from dotenv import load_dotenv

from app.config import load_config
from app.football_client import FootballDataClient
from app.match_service import get_relevant_matches
from app.storage import NotificationStore
from app.telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("check_matches")


def _build_message(event) -> str:
    local_time = event.starts_at.strftime("%H:%M")
    lines = [
        f"\U000026bd ¡Hoy juega {event.team}!",
        "",
        f"Partido: {event.title}",
        f"Hora: {local_time}",
    ]
    if event.radio:
        lines.append(f"Escúchalo en: {event.radio.label}")
        lines.append(f"Link: {event.radio.url}")
    return "\n".join(lines)


def main():
    load_dotenv()
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not api_key:
        logger.error("FOOTBALL_DATA_API_KEY is not set in .env")
        sys.exit(1)

    config = load_config()
    client = FootballDataClient(api_key=api_key)
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    store = NotificationStore()

    events = get_relevant_matches(config, client)
    if not events:
        logger.info("No relevant matches found for today")
        return

    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    window_minutes = config.notification_window_minutes

    for event in events:
        diff = (event.starts_at - now).total_seconds()
        if diff < 0:
            logger.info("Match already started: %s", event.id)
            continue
        minutes_until = diff / 60
        if minutes_until > window_minutes:
            logger.debug(
                "Match %s is %.0f minutes away, window is %d min",
                event.id,
                minutes_until,
                window_minutes,
            )
            continue

        if store.is_sent(event.id):
            logger.info("Notification already sent for %s", event.id)
            continue

        message = _build_message(event)
        success = notifier.send_message(message)
        if success:
            store.mark_sent(event.id)
            logger.info("Notification sent for %s", event.id)
        else:
            logger.error("Failed to send notification for %s", event.id)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception("Unhandled error in check_matches: %s", e)
        sys.exit(1)
