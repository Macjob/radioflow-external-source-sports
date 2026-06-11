import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class NotificationStore:
    def __init__(self, path: str = "sent_notifications.json"):
        self.path = Path(path)
        self._ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            logger.debug("Notification store %s not found, starting fresh", self.path)
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._ids = set(data)
            else:
                logger.warning("Unexpected format in %s, resetting", self.path)
                self._ids = set()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s, resetting", self.path, e)
            self._ids = set()

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._ids), f, ensure_ascii=False)
        except OSError as e:
            logger.error("Failed to write %s: %s", self.path, e)

    def is_sent(self, match_id: str) -> bool:
        return match_id in self._ids

    def mark_sent(self, match_id: str) -> None:
        self._ids.add(match_id)
        self._save()
