import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.chile_sports.models import ScheduleSnapshot, SourceAnnouncement
from app.sports_provider import (
    Competition,
    CompletedMatch,
    ScheduledMatch,
    Team,
    TeamRef,
)


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class ChileSportsStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS sports_competitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    country TEXT NOT NULL,
                    season TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_external_id TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sports_teams (
                    id TEXT PRIMARY KEY,
                    competition_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_external_id TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY (competition_id) REFERENCES sports_competitions(id)
                );
                CREATE TABLE IF NOT EXISTS sports_matches (
                    id TEXT PRIMARY KEY,
                    competition_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    matchweek TEXT NOT NULL,
                    source_date TEXT NOT NULL,
                    starts_at TEXT,
                    time_confirmed INTEGER NOT NULL,
                    home_team_id TEXT NOT NULL,
                    away_team_id TEXT NOT NULL,
                    venue TEXT,
                    status TEXT NOT NULL,
                    home_score INTEGER,
                    away_score INTEGER,
                    source TEXT NOT NULL,
                    source_external_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_note TEXT,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (competition_id) REFERENCES sports_competitions(id),
                    FOREIGN KEY (home_team_id) REFERENCES sports_teams(id),
                    FOREIGN KEY (away_team_id) REFERENCES sports_teams(id)
                );
                CREATE INDEX IF NOT EXISTS sports_matches_schedule_idx
                    ON sports_matches (competition_id, status, starts_at);
                CREATE TABLE IF NOT EXISTS sports_source_mappings (
                    source TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    internal_id TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (source, entity_type, external_id)
                );
                CREATE TABLE IF NOT EXISTS sports_announcements (
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    change_type TEXT,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (source, external_id)
                );
                CREATE TABLE IF NOT EXISTS sports_sync_state (
                    source TEXT PRIMARY KEY,
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    last_modified TEXT,
                    last_error TEXT,
                    item_count INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def store_snapshot(
        self,
        snapshot: ScheduleSnapshot,
        *,
        source: str,
        fetched_at: datetime,
        last_modified: str | None,
    ) -> tuple[int, int]:
        fetched_text = _utc_text(fetched_at)
        discovered = 0
        changed = 0
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            competition = snapshot.competition
            connection.execute(
                """
                INSERT INTO sports_competitions
                    (id, name, country, season, source, source_external_id, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    country=excluded.country,
                    season=excluded.season,
                    source=excluded.source,
                    source_external_id=excluded.source_external_id,
                    fetched_at=excluded.fetched_at
                """,
                (
                    competition.id,
                    competition.name,
                    competition.country,
                    competition.season,
                    source,
                    competition.external_id,
                    fetched_text,
                ),
            )
            self._upsert_mapping(
                connection,
                source,
                "competition",
                competition.external_id,
                competition.id,
                fetched_text,
            )
            for team in snapshot.teams:
                connection.execute(
                    """
                    INSERT INTO sports_teams
                        (id, competition_id, name, source, source_external_id, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        source=excluded.source,
                        source_external_id=excluded.source_external_id,
                        fetched_at=excluded.fetched_at
                    """,
                    (team.id, competition.id, team.name, source, team.external_id, fetched_text),
                )
                self._upsert_mapping(
                    connection,
                    source,
                    "team",
                    team.external_id,
                    team.id,
                    fetched_text,
                )
            for match in snapshot.matches:
                existing = connection.execute(
                    """
                    SELECT matchweek, source_date, starts_at, time_confirmed, venue, status,
                           home_score, away_score, source_external_id
                    FROM sports_matches WHERE id = ?
                    """,
                    (match.id,),
                ).fetchone()
                values = (
                    match.matchweek,
                    match.source_date.isoformat(),
                    _utc_text(match.starts_at),
                    int(match.time_confirmed),
                    match.venue,
                    match.status,
                    match.home_score,
                    match.away_score,
                    match.external_id,
                )
                if existing is None:
                    discovered += 1
                elif tuple(existing) != values:
                    changed += 1
                connection.execute(
                    """
                    INSERT INTO sports_matches (
                        id, competition_id, season, matchweek, source_date, starts_at,
                        time_confirmed, home_team_id, away_team_id, venue, status,
                        home_score, away_score, source, source_external_id, source_url,
                        source_note, fetched_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        matchweek=excluded.matchweek,
                        source_date=excluded.source_date,
                        starts_at=excluded.starts_at,
                        time_confirmed=excluded.time_confirmed,
                        venue=excluded.venue,
                        status=excluded.status,
                        home_score=excluded.home_score,
                        away_score=excluded.away_score,
                        source_external_id=excluded.source_external_id,
                        source_url=excluded.source_url,
                        source_note=excluded.source_note,
                        fetched_at=excluded.fetched_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        match.id,
                        match.competition_id,
                        match.season,
                        match.matchweek,
                        match.source_date.isoformat(),
                        _utc_text(match.starts_at),
                        int(match.time_confirmed),
                        match.home_team.id,
                        match.away_team.id,
                        match.venue,
                        match.status,
                        match.home_score,
                        match.away_score,
                        source,
                        match.external_id,
                        match.source_url,
                        match.note,
                        fetched_text,
                        fetched_text,
                    ),
                )
                self._upsert_mapping(
                    connection,
                    source,
                    "match",
                    match.external_id,
                    match.id,
                    fetched_text,
                )
            connection.execute(
                """
                INSERT INTO sports_sync_state
                    (source, last_attempt_at, last_success_at, last_modified, last_error, item_count)
                VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    last_modified=excluded.last_modified,
                    last_error=NULL,
                    item_count=excluded.item_count
                """,
                (source, fetched_text, fetched_text, last_modified, len(snapshot.matches)),
            )
        return discovered, changed

    @staticmethod
    def _upsert_mapping(
        connection,
        source: str,
        entity_type: str,
        external_id: str,
        internal_id: str,
        seen_at: str,
    ):
        connection.execute(
            """
            INSERT INTO sports_source_mappings
                (source, entity_type, external_id, internal_id, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, entity_type, external_id) DO UPDATE SET
                internal_id=excluded.internal_id,
                last_seen_at=excluded.last_seen_at
            """,
            (source, entity_type, external_id, internal_id, seen_at, seen_at),
        )

    def record_not_modified(self, source: str, checked_at: datetime):
        checked_text = _utc_text(checked_at)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sports_sync_state (source, last_attempt_at, last_success_at, item_count)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    last_error=NULL
                """,
                (source, checked_text, checked_text),
            )

    def record_failure(self, source: str, attempted_at: datetime, error: str):
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sports_sync_state (source, last_attempt_at, last_error, item_count)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    last_error=excluded.last_error
                """,
                (source, _utc_text(attempted_at), error[:500]),
            )

    def store_announcements(
        self,
        announcements: list[SourceAnnouncement],
        *,
        source: str,
        fetched_at: datetime,
    ):
        fetched_text = _utc_text(fetched_at)
        with self._lock, self._connect() as connection:
            for item in announcements:
                connection.execute(
                    """
                    INSERT INTO sports_announcements (
                        source, external_id, title, published_at, modified_at, url,
                        content, change_type, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, external_id) DO UPDATE SET
                        title=excluded.title,
                        modified_at=excluded.modified_at,
                        url=excluded.url,
                        content=excluded.content,
                        change_type=excluded.change_type,
                        fetched_at=excluded.fetched_at
                    """,
                    (
                        source,
                        item.external_id,
                        item.title,
                        _utc_text(item.published_at),
                        _utc_text(item.modified_at),
                        item.url,
                        item.content,
                        item.change_type,
                        fetched_text,
                    ),
                )
            connection.execute(
                """
                INSERT INTO sports_sync_state
                    (source, last_attempt_at, last_success_at, last_error, item_count)
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    last_error=NULL,
                    item_count=excluded.item_count
                """,
                (source, fetched_text, fetched_text, len(announcements)),
            )

    def sync_state(self, source: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sports_sync_state WHERE source = ?",
                (source,),
            ).fetchone()
        return dict(row) if row else None

    def has_data(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM sports_matches LIMIT 1").fetchone()
        return row is not None

    def next_scheduled_start(self, now: datetime) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT starts_at FROM sports_matches
                WHERE status = 'scheduled' AND time_confirmed = 1 AND starts_at >= ?
                ORDER BY starts_at LIMIT 1
                """,
                (_utc_text(now),),
            ).fetchone()
        return _utc_datetime(row["starts_at"]) if row else None

    def get_competitions(self) -> list[Competition]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, country, season FROM sports_competitions ORDER BY name"
            ).fetchall()
        return [Competition(row["id"], row["name"], row["country"], row["season"]) for row in rows]

    def get_teams(self, competition_id: str) -> list[Team]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name FROM sports_teams WHERE competition_id = ? ORDER BY name",
                (competition_id,),
            ).fetchall()
        return [Team(row["id"], row["name"]) for row in rows]

    def get_scheduled_matches(
        self,
        competition_id: str,
        starts_after: datetime,
        starts_before: datetime,
    ) -> list[ScheduledMatch]:
        rows = self._match_rows(competition_id, "scheduled", starts_after, starts_before)
        return [
            ScheduledMatch(
                id=row["id"],
                competition_id=row["competition_id"],
                starts_at=_utc_datetime(row["starts_at"]),
                home_team=TeamRef(row["home_team_id"], row["home_team_name"]),
                away_team=TeamRef(row["away_team_id"], row["away_team_name"]),
                venue=row["venue"],
            )
            for row in rows
        ]

    def get_results(
        self,
        competition_id: str,
        starts_after: datetime,
        starts_before: datetime,
    ) -> list[CompletedMatch]:
        rows = self._match_rows(competition_id, "finished", starts_after, starts_before)
        return [
            CompletedMatch(
                id=row["id"],
                competition_id=row["competition_id"],
                starts_at=_utc_datetime(row["starts_at"]),
                home_team=TeamRef(row["home_team_id"], row["home_team_name"]),
                away_team=TeamRef(row["away_team_id"], row["away_team_name"]),
                home_score=row["home_score"],
                away_score=row["away_score"],
            )
            for row in rows
        ]

    def _match_rows(
        self,
        competition_id: str,
        status: str,
        starts_after: datetime,
        starts_before: datetime,
    ):
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT m.*, home.name AS home_team_name, away.name AS away_team_name
                FROM sports_matches m
                JOIN sports_teams home ON home.id = m.home_team_id
                JOIN sports_teams away ON away.id = m.away_team_id
                WHERE m.competition_id = ? AND m.status = ? AND m.time_confirmed = 1
                  AND m.starts_at >= ? AND m.starts_at <= ?
                ORDER BY m.starts_at
                """,
                (
                    competition_id,
                    status,
                    _utc_text(starts_after),
                    _utc_text(starts_before),
                ),
            ).fetchall()
