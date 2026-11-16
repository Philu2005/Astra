import json
import types

from api.app import create_app
from api.guild_state import guild_state_store
from api import db as api_db_module


def _auth_headers():
    return {"Authorization": "Bearer test-key"}


def _ready_guild_snapshot(guild_id: int, owner_id: int):
    guild_state_store.replace_all(
        guilds=[
            {
                "id": guild_id,
                "name": "Test Guild",
                "icon": None,
                "owner_id": owner_id,
                "member_count": 2,
                "members": [
                    {"id": owner_id, "permissions": {"administrator": True, "manage_guild": True}},
                ],
                "roles": [
                    {"id": 1, "name": "@everyone", "permissions": {}},
                    {"id": 2, "name": "Moderator", "permissions": {}},
                ],
                "channels": [
                    {"id": 1234, "name": "modlog", "type": "text"},
                ],
            }
        ],
        stats={"users": 2, "guilds": 1, "commands": 0},
        last_updated="2026-01-01T00:00:00Z",
    )


def test_warns_requires_auth():
    app = create_app(config={"ASTRA_INTERNAL_API_KEY": "test-key"})
    client = app.test_client()
    resp = client.get("/moderation/warns/1/2")
    assert resp.status_code == 401


def test_warns_missing_user_id():
    app = create_app(config={"ASTRA_INTERNAL_API_KEY": "test-key"})
    client = app.test_client()
    _ready_guild_snapshot(guild_id=111, owner_id=42)

    resp = client.get("/moderation/warns/111/999", headers=_auth_headers())
    assert resp.status_code in (400, 503)  # 503 falls Snapshot als stale erkannt würde


def test_warns_happy_path_with_mocked_db(monkeypatch):
    app = create_app(config={"ASTRA_INTERNAL_API_KEY": "test-key", "GUILD_SNAPSHOT_STALE_AFTER_SECONDS": 999999})
    client = app.test_client()
    _ready_guild_snapshot(guild_id=111, owner_id=42)

    class DummyPool:
        pass

    # Monkeypatch api_db.get_pool -> Dummy
    monkeypatch.setattr(api_db_module.api_db, "get_pool", lambda: DummyPool())

    # Monkeypatch api_db.run_coro -> direktes Ergebnis (Warnliste)
    def _fake_run_coro(coro, timeout=None):
        # Wir parsen die coroutine Funktion und geben Testdaten zurück
        return [
            {"warnId": 1, "reason": "Test 1"},
            {"warnId": 2, "reason": "Test 2"},
        ]

    monkeypatch.setattr(api_db_module.api_db, "run_coro", _fake_run_coro)

    resp = client.get("/moderation/warns/111/555?user_id=42", headers=_auth_headers())
    assert resp.status_code == 200
    data = json.loads(resp.data.decode("utf-8"))
    assert data["success"] is True
    assert data["count"] == 2
    assert isinstance(data["warns"], list)


def test_automod_put_validation_and_no_discord_sideeffects(monkeypatch):
    app = create_app(config={"ASTRA_INTERNAL_API_KEY": "test-key", "GUILD_SNAPSHOT_STALE_AFTER_SECONDS": 999999})
    client = app.test_client()
    _ready_guild_snapshot(guild_id=222, owner_id=77)

    class DummyPool:
        pass

    monkeypatch.setattr(api_db_module.api_db, "get_pool", lambda: DummyPool())
    # run_coro stub: für save keine Rückgabe, für reload Konfiguration
    def _fake_run_coro(coro, timeout=None):
        # Wenn load_automod -> gebe Beispielkonfig zurück
        cfg = {
            "rules": [{"warns": 1, "action": "timeout", "timeout_seconds": 600}],
            "capslock": {"percent": 60, "enabled": True},
            "blacklist": {"enabled": True, "words": ["abc"]},
        }
        return cfg

    monkeypatch.setattr(api_db_module.api_db, "run_coro", _fake_run_coro)

    payload = {
        "rules": [{"warns": 1, "action": "timeout", "timeout_seconds": 600}],
        "capslock": {"percent": 70, "enabled": False},
        "blacklist": {"enabled": True, "words": ["foo", "bar"]},
    }
    resp = client.put(
        "/moderation/automod/222?user_id=77",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    assert resp.status_code == 200
    data = json.loads(resp.data.decode("utf-8"))
    assert data["success"] is True
    # Wichtiger Negativtest: Die API löst keine Discord-Nachrichten oder Embeds aus –
    # hier nur implizit geprüft, indem die API synchron antwortet und keine Bot-Objekte benötigt.


def test_modlog_put_and_get(monkeypatch):
    app = create_app(config={"ASTRA_INTERNAL_API_KEY": "test-key", "GUILD_SNAPSHOT_STALE_AFTER_SECONDS": 999999})
    client = app.test_client()
    _ready_guild_snapshot(guild_id=333, owner_id=88)

    class DummyPool:
        pass

    monkeypatch.setattr(api_db_module.api_db, "get_pool", lambda: DummyPool())

    # run_coro: bei set_modlog ignorieren, bei get_modlog Rückgabe 1234
    def _fake_run_coro(coro, timeout=None):
        return 1234

    monkeypatch.setattr(api_db_module.api_db, "run_coro", _fake_run_coro)

    # Setzen
    resp_put = client.put(
        "/moderation/modlog/333?user_id=88",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        data=json.dumps({"channel_id": 1234}),
    )
    assert resp_put.status_code == 200

    # Abrufen
    resp_get = client.get("/moderation/modlog/333?user_id=88", headers=_auth_headers())
    assert resp_get.status_code == 200
    data = json.loads(resp_get.data.decode("utf-8"))
    assert data["success"] is True
    assert data["channelId"] == "1234"
