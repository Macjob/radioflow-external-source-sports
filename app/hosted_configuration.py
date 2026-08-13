import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

OPAQUE_PATTERN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
SESSION_TTL = timedelta(minutes=10)
DOMAIN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9:-]{1,159}$")


@dataclass(frozen=True)
class PendingSession:
    id: str
    state: str
    callback_url: str
    mode: str
    existing_config_hash: str | None
    expires_at: datetime


@dataclass(frozen=True)
class StoredConfiguration:
    config_hash: str
    competition: dict[str, Any]
    teams: list[dict[str, Any]]
    events: list[str]
    summary: dict[str, Any]


class HostedConfigurationStore:
    def __init__(self, database_path: str | Path, signing_secret: str):
        if len(signing_secret.encode("utf-8")) < 32:
            raise ValueError("SPORTS_CONFIG_SIGNING_SECRET must contain at least 32 bytes")
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_secret = signing_secret.encode("utf-8")
        self._lock = threading.RLock()
        self._initialize()

    def create_session(
        self,
        state: str,
        callback_url: str,
        mode: str,
        existing_config_id: str | None = None,
    ) -> PendingSession:
        validate_opaque(state, "state")
        validate_callback_url(callback_url)
        if mode not in {"install", "reconfigure"}:
            raise ValueError("invalid configuration mode")
        existing_hash = hash_config_id(existing_config_id) if existing_config_id else None
        if mode == "reconfigure" and (not existing_hash or not self.get_configuration(existing_config_id)):
            raise ValueError("unknown configuration")
        session_id = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + SESSION_TTL
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO configuration_sessions
                    (id, state, callback_url, mode, existing_config_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    state,
                    callback_url,
                    mode,
                    existing_hash,
                    expires_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return PendingSession(session_id, state, callback_url, mode, existing_hash, expires_at)

    def get_session(self, session_id: str) -> PendingSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, state, callback_url, mode, existing_config_hash, expires_at FROM configuration_sessions WHERE id = ? AND completed_at IS NULL",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        expires_at = datetime.fromisoformat(row[5])
        if expires_at <= datetime.now(timezone.utc):
            return None
        return PendingSession(row[0], row[1], row[2], row[3], row[4], expires_at)

    def save_configuration(
        self,
        session_id: str,
        competition: dict[str, Any],
        teams: list[dict[str, Any]],
        events: list[str],
    ) -> tuple[str, str, str, dict[str, Any]]:
        session = self.get_session(session_id)
        if not session:
            raise ValueError("configuration session is invalid or expired")
        normalized = validate_configuration(competition, teams, events)
        code = secrets.token_urlsafe(32)
        config_id = self._derive_config_id(code)
        config_hash = hash_config_id(config_id)
        code_hash = hash_config_id(code)
        summary = {
            "title": "Sports Notifications",
            "lines": [
                f"Competition: {normalized['competition']['name']}",
                "Teams: " + ", ".join(team["name"] for team in normalized["teams"]),
                "Events: Match scheduled",
            ],
        }
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT completed_at FROM configuration_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not active or active[0] is not None:
                raise ValueError("configuration session was already completed")
            if session.existing_config_hash:
                connection.execute(
                    "UPDATE configurations SET active = 0, updated_at = ? WHERE config_hash = ?",
                    (now, session.existing_config_hash),
                )
            connection.execute(
                """
                INSERT INTO configurations
                    (config_hash, competition_json, teams_json, events_json, summary_json, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    config_hash,
                    json.dumps(normalized["competition"], separators=(",", ":")),
                    json.dumps(normalized["teams"], separators=(",", ":")),
                    json.dumps(normalized["events"], separators=(",", ":")),
                    json.dumps(summary, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE configuration_sessions SET code_hash = ?, completed_at = ? WHERE id = ?",
                (code_hash, now, session_id),
            )
            connection.commit()
        return code, session.state, session.callback_url, summary

    def exchange_code(self, code: str) -> tuple[str, dict[str, Any]]:
        validate_opaque(code, "code")
        code_hash = hash_config_id(code)
        config_id = self._derive_config_id(code)
        config_hash = hash_config_id(config_id)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM configuration_sessions
                WHERE code_hash = ? AND exchanged_at IS NULL AND completed_at IS NOT NULL AND expires_at > ?
                """,
                (code_hash, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
            if not row:
                raise ValueError("configuration code is invalid, expired, or already used")
            configuration = connection.execute(
                "SELECT summary_json FROM configurations WHERE config_hash = ? AND active = 1",
                (config_hash,),
            ).fetchone()
            if not configuration:
                raise ValueError("configuration is unavailable")
            connection.execute(
                "UPDATE configuration_sessions SET exchanged_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row[0]),
            )
            connection.commit()
        return config_id, json.loads(configuration[0])

    def get_configuration(self, config_id: str | None) -> StoredConfiguration | None:
        if not config_id:
            return None
        try:
            validate_opaque(config_id, "configId")
        except ValueError:
            return None
        config_hash = hash_config_id(config_id)
        return self.get_configuration_by_hash(config_hash)

    def get_configuration_by_hash(self, config_hash: str) -> StoredConfiguration | None:
        if len(config_hash) != 64:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT competition_json, teams_json, events_json, summary_json
                FROM configurations WHERE config_hash = ? AND active = 1
                """,
                (config_hash,),
            ).fetchone()
        if not row:
            return None
        return StoredConfiguration(
            config_hash=config_hash,
            competition=json.loads(row[0]),
            teams=json.loads(row[1]),
            events=json.loads(row[2]),
            summary=json.loads(row[3]),
        )

    def _derive_config_id(self, code: str) -> str:
        digest = hmac.new(self.signing_secret, f"radioflow-config:{code}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS configurations (
                    config_hash TEXT PRIMARY KEY,
                    competition_json TEXT NOT NULL,
                    teams_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuration_sessions (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    callback_url TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    existing_config_hash TEXT,
                    code_hash TEXT UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    exchanged_at TEXT
                );
                CREATE INDEX IF NOT EXISTS configuration_sessions_expiry_idx
                    ON configuration_sessions(expires_at);
                """
            )


def hash_config_id(config_id: str) -> str:
    return hashlib.sha256(config_id.encode("utf-8")).hexdigest()


def validate_opaque(value: str, label: str):
    if not 32 <= len(value) <= 256 or any(character not in OPAQUE_PATTERN for character in value):
        raise ValueError(f"invalid {label}")


def validate_callback_url(callback_url: str):
    parsed = urlparse(callback_url)
    allowed = {
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "SPORTS_ALLOWED_CALLBACK_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://testserver",
        ).split(",")
        if origin.strip()
    }
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.username or parsed.password or origin not in allowed:
        raise ValueError("callback origin is not allowed")
    if parsed.path != "/api/addons/configuration/callback" or parsed.query or parsed.fragment:
        raise ValueError("callback path is invalid")


def validate_configuration(
    competition: dict[str, Any],
    teams: list[dict[str, Any]],
    events: list[str],
) -> dict[str, Any]:
    competition_id = competition.get("id")
    season = competition.get("season")
    name = str(competition.get("name", "")).strip()
    if (
        not isinstance(competition_id, str)
        or not DOMAIN_ID_PATTERN.fullmatch(competition_id)
        or not isinstance(season, str)
        or not 1 <= len(season) <= 20
        or not name
    ):
        raise ValueError("invalid competition")
    if not 1 <= len(teams) <= 20:
        raise ValueError("select between 1 and 20 teams")
    normalized_teams = []
    seen = set()
    for team in teams:
        team_id = team.get("id")
        team_name = str(team.get("name", "")).strip()
        if (
            not isinstance(team_id, str)
            or not DOMAIN_ID_PATTERN.fullmatch(team_id)
            or not team_name
            or team_id in seen
        ):
            raise ValueError("invalid team selection")
        seen.add(team_id)
        normalized_teams.append({"id": team_id, "name": team_name[:120]})
    if events != ["match.scheduled"]:
        raise ValueError("this release supports only match.scheduled")
    return {
        "competition": {"id": competition_id, "name": name[:120], "season": season},
        "teams": normalized_teams,
        "events": events,
    }
