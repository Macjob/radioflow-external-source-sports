import logging

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: int = 10):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._url = TELEGRAM_API.format(token=bot_token)

    def send_message(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram not configured, skipping notification")
            return False
        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("ok"):
                logger.info("Telegram notification sent successfully")
                return True
            logger.error("Telegram API returned error: %s", result.get("description", "unknown"))
            return False
        except requests.ConnectionError as e:
            logger.error("Connection error sending Telegram message: %s", e)
            return False
        except requests.Timeout as e:
            logger.error("Timeout sending Telegram message: %s", e)
            return False
        except requests.HTTPError as e:
            logger.error("HTTP error sending Telegram message: %s", e)
            return False
        except ValueError as e:
            logger.error("Invalid JSON response from Telegram: %s", e)
            return False
