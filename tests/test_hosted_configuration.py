import sqlite3

import pytest

from app.hosted_configuration import HostedConfigurationStore, hash_config_id


def selection():
    return (
        {"id": "chile-primera-division", "name": "Primera División de Chile", "season": "2026"},
        [{"id": "chile-primera-division:colo-colo", "name": "Colo-Colo"}],
        ["match.scheduled"],
    )


def test_store_persists_only_config_hash_and_supports_all_bearer_operations(tmp_path):
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
    assert store.get_configuration(config_id) is None
    assert store.get_configuration(new_config_id).teams[0]["id"] == "chile-primera-division:universidad-de-chile"


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
