import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.hosted_configuration import (
    ConfigurationTransitionError,
    HostedConfigurationStore,
    hash_config_id,
)


def selection():
    return (
        {"id": "chile-primera-division", "name": "Primera División de Chile", "season": "2026"},
        [{"id": "chile-primera-division:colo-colo", "name": "Colo-Colo"}],
        ["match.scheduled"],
    )


def test_store_persists_only_config_hash_and_supports_safe_reconfiguration(tmp_path):
    path = tmp_path / "sports.db"
    store = HostedConfigurationStore(path, "test-secret-" * 4)
    pending = store.create_session(
        "s" * 43,
        "http://testserver/api/addons/configuration/callback",
        "install",
    )
    code, _, _, _ = store.save_configuration(pending.id, *selection())
    config_id, _ = store.exchange_code(code)

    stored = store.get_configuration(config_id)
    assert stored is not None
    assert stored.teams == [{"id": "chile-primera-division:colo-colo", "name": "Colo-Colo"}]
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT config_hash FROM configurations").fetchone()
        dump = " ".join(connection.iterdump())
    assert row[0] == hash_config_id(config_id)
    assert config_id not in dump
    assert code not in dump

    reconfigure = store.create_session(
        "r" * 43,
        "http://testserver/api/addons/configuration/callback",
        "reconfigure",
        existing_config_id=config_id,
    )
    new_code, _, _, _ = store.save_configuration(
        reconfigure.id,
        {"id": "chile-primera-division", "name": "Primera División de Chile", "season": "2026"},
        [{"id": "chile-primera-division:universidad-de-chile", "name": "Universidad de Chile"}],
        ["match.scheduled"],
    )
    new_config_id, _ = store.exchange_code(new_code)
    assert store.get_configuration(config_id) is not None
    assert store.get_configuration(new_config_id) is None

    store.finalize_configuration(new_config_id, "commit")
    store.finalize_configuration(new_config_id, "commit")

    assert store.get_configuration(config_id) is None
    assert store.get_configuration(new_config_id).teams[0]["id"] == "chile-primera-division:universidad-de-chile"
    with sqlite3.connect(path) as connection:
        dump = " ".join(connection.iterdump())
    assert all(value not in dump for value in (config_id, new_config_id, code, new_code))
    with pytest.raises(ConfigurationTransitionError, match="already committed"):
        store.finalize_configuration(new_config_id, "rollback")
    assert store.get_configuration(new_config_id) is not None


def test_store_rejects_unknown_reconfiguration_and_replayed_exchange(tmp_path):
    store = HostedConfigurationStore(tmp_path / "sports.db", "test-secret-" * 4)
    with pytest.raises(ValueError, match="unknown configuration"):
        store.create_session(
            "s" * 43,
            "http://testserver/api/addons/configuration/callback",
            "reconfigure",
            existing_config_id="z" * 43,
        )
    pending = store.create_session("s" * 43, "http://testserver/api/addons/configuration/callback", "install")
    code, _, _, _ = store.save_configuration(pending.id, *selection())
    store.exchange_code(code)
    with pytest.raises(ValueError, match="already used"):
        store.exchange_code(code)


def test_reconfiguration_rollback_keeps_previous_configuration_active(tmp_path):
    store = HostedConfigurationStore(tmp_path / "sports.db", "test-secret-" * 4)
    install = store.create_session("s" * 43, "http://testserver/api/addons/configuration/callback", "install")
    code, _, _, _ = store.save_configuration(install.id, *selection())
    config_id, _ = store.exchange_code(code)

    reconfigure = store.create_session(
        "r" * 43,
        "http://testserver/api/addons/configuration/callback",
        "reconfigure",
        existing_config_id=config_id,
    )
    new_code, _, _, _ = store.save_configuration(
        reconfigure.id,
        {"id": "chile-primera-division", "name": "Primera División de Chile", "season": "2026"},
        [{"id": "chile-primera-division:universidad-de-chile", "name": "Universidad de Chile"}],
        ["match.scheduled"],
    )
    new_config_id, _ = store.exchange_code(new_code)

    store.finalize_configuration(new_config_id, "rollback")
    store.finalize_configuration(new_config_id, "rollback")

    assert store.get_configuration(config_id) is not None
    assert store.get_configuration(new_config_id) is None
    with pytest.raises(ValueError, match="already rolled back"):
        store.finalize_configuration(new_config_id, "commit")


def test_existing_database_is_migrated_for_safe_finalization(tmp_path):
    path = tmp_path / "sports.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE configurations (
                config_hash TEXT PRIMARY KEY,
                competition_json TEXT NOT NULL,
                teams_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        competition, teams, events = selection()
        for config_id, active in [("a" * 43, 1), ("b" * 43, 0)]:
            connection.execute(
                "INSERT INTO configurations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (hash_config_id(config_id), json.dumps(competition), json.dumps(teams),
                 json.dumps(events), "{}", active, "created", "updated"),
            )
        original = connection.execute("SELECT * FROM configurations ORDER BY config_hash").fetchall()

    for _ in range(2):
        store = HostedConfigurationStore(path, "test-secret-" * 4)
        assert store.get_configuration("a" * 43) is not None
        assert store.get_configuration("b" * 43) is None
        store.finalize_configuration("a" * 43, "commit")
        with pytest.raises(ConfigurationTransitionError):
            store.finalize_configuration("a" * 43, "rollback")
        with pytest.raises(ConfigurationTransitionError):
            store.finalize_configuration("b" * 43, "commit")

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(configurations)")}
    assert {"transition_state", "replaces_config_hash"}.issubset(columns)
    with sqlite3.connect(path) as connection:
        migrated = connection.execute("SELECT * FROM configurations ORDER BY config_hash").fetchall()
    assert [row[:8] for row in migrated] == original
    assert all(row[8:] == (None, None) for row in migrated)


def issue_configuration(store, existing_config_id=None, *, exchange=True):
    session = store.create_session(
        "s" * 43, "http://testserver/api/addons/configuration/callback",
        "reconfigure" if existing_config_id else "install", existing_config_id,
    )
    code, _, _, _ = store.save_configuration(session.id, *selection())
    return store.exchange_code(code)[0] if exchange else code


def test_concurrent_commits_across_store_instances(tmp_path):
    path = tmp_path / "sports.db"
    stores = [HostedConfigurationStore(path, "test-secret-" * 4) for _ in range(2)]
    old = issue_configuration(stores[0])
    first = issue_configuration(stores[0], old)
    barrier = Barrier(2)

    def commit(index):
        barrier.wait(timeout=5)
        try:
            stores[index].finalize_configuration(first, "commit")
            return True
        except ConfigurationTransitionError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, range(2)))
    assert sum(results) == 2
    assert stores[0].get_configuration(old) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM configurations WHERE active = 1").fetchone()[0] == 1


@pytest.mark.parametrize("outcome", ["commit", "rollback"])
def test_simultaneous_reconfigurations_reserve_only_one_exchange(tmp_path, outcome):
    path = tmp_path / "sports.db"
    stores = [HostedConfigurationStore(path, "test-secret-" * 4) for _ in range(2)]
    old = issue_configuration(stores[0])
    codes = [issue_configuration(store, old, exchange=False) for store in stores]
    barrier = Barrier(2)

    def exchange(index):
        barrier.wait(timeout=5)
        try:
            return stores[index].exchange_code(codes[index])[0]
        except ConfigurationTransitionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(exchange, range(2)))
    assert sum(value is not None for value in results) == 1
    winner = next(value for value in results if value is not None)
    assert stores[0].get_configuration(old) is not None
    assert stores[0].get_configuration(winner) is None
    stores[0].finalize_configuration(winner, outcome)
    loser_code = codes[results.index(None)]
    if outcome == "commit":
        with pytest.raises(ConfigurationTransitionError, match="no longer active"):
            stores[0].exchange_code(loser_code)
        assert stores[0].get_configuration(winner) is not None
        assert stores[0].get_configuration(old) is None
    else:
        replacement, _ = stores[0].exchange_code(loser_code)
        stores[0].finalize_configuration(replacement, "commit")
        assert stores[0].get_configuration(replacement) is not None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM configurations WHERE active = 1").fetchone()[0] == 1


def test_failed_commit_rolls_back_both_updates_and_can_retry(tmp_path):
    path = tmp_path / "sports.db"
    store = HostedConfigurationStore(path, "test-secret-" * 4)
    old = issue_configuration(store)
    new = issue_configuration(store, old)
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TRIGGER fail_activation BEFORE UPDATE OF active ON configurations
            WHEN NEW.active = 1
            BEGIN SELECT RAISE(ABORT, 'injected activation failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected activation failure"):
        store.finalize_configuration(new, "commit")
    assert store.get_configuration(old) is not None
    assert store.get_configuration(new) is None
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER fail_activation")
    store.finalize_configuration(new, "commit")
    assert store.get_configuration(old) is None
    assert store.get_configuration(new) is not None


def test_install_ignores_existing_configuration_header(tmp_path):
    store = HostedConfigurationStore(tmp_path / "sports.db", "test-secret-" * 4)
    old = issue_configuration(store)
    session = store.create_session(
        "s" * 43, "http://testserver/api/addons/configuration/callback", "install", old,
    )
    code, _, _, _ = store.save_configuration(session.id, *selection())
    new, _ = store.exchange_code(code)
    assert store.get_configuration(old) is not None
    assert store.get_configuration(new) is not None
