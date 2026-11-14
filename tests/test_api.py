import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
import discord
from threading import Lock
from api.app import create_app, run_flask
from api.auth import get_expected_api_key, verify_service_token
from api.permissions import validate_user_id, check_user_guild_permissions, fetch_member_threadsafe


class MockPermissions:
    def __init__(self, administrator=False, manage_guild=False):
        self.administrator = administrator
        self.manage_guild = manage_guild


class MockRole:
    def __init__(self, role_id: int, name: str):
        self.id = role_id
        self.name = name


class MockIcon:
    def __init__(self, key="mock_icon_key"):
        self.key = key


class MockMember:
    def __init__(self, user_id: int, guild_permissions: MockPermissions):
        self.id = user_id
        self.guild_permissions = guild_permissions


class MockGuild:
    def __init__(self, guild_id: int, name: str, owner_id: int, member_count: int = 10, icon_key: str | None = "icon123"):
        self.id = guild_id
        self.name = name
        self.owner_id = owner_id
        self.member_count = member_count
        self.icon = MockIcon(icon_key) if icon_key else None
        self.channels = [MagicMock(id=1), MagicMock(id=2)]
        self.roles = [
            MockRole(guild_id, "@everyone"),
            MockRole(1001, "Admin"),
            MockRole(1002, "Moderator"),
        ]
        self._members = {}

    def add_member(self, member: MockMember):
        self._members[member.id] = member

    def get_member(self, user_id: int):
        return self._members.get(user_id)

    async def fetch_member(self, user_id: int):
        member = self.get_member(user_id)
        if member is None:
            raise discord.NotFound(MagicMock(), "User not found")
        return member


class InternalApiTestCase(unittest.TestCase):
    def setUp(self):
        self.test_api_key = "test_super_secret_api_key_12345"
        self.guild_cache = {}
        self.guild_cache_lock = Lock()
        self.mock_bot = MagicMock()
        self.mock_bot.is_ready.return_value = True
        self.mock_bot.bot_ready = True
        # loop is None by default in test unless specifically tested, so fetch_member returns None immediately
        self.mock_bot.loop = None

        self.app = create_app(
            bot=self.mock_bot,
            guild_cache=self.guild_cache,
            guild_cache_lock=self.guild_cache_lock,
            config={"ASTRA_INTERNAL_API_KEY": self.test_api_key, "TESTING": True},
        )
        self.client = self.app.test_client()
        self.auth_headers = {"Authorization": f"Bearer {self.test_api_key}"}

        # Setup Test Guilds
        self.guild1 = MockGuild(111, "Astra Community", owner_id=999, member_count=100)
        self.guild2 = MockGuild(222, "Other Server", owner_id=888, member_count=50)

        # Members for guild1
        self.guild1.add_member(MockMember(999, MockPermissions(administrator=True, manage_guild=True)))  # Owner
        self.guild1.add_member(MockMember(123, MockPermissions(administrator=True, manage_guild=False)))  # Admin
        self.guild1.add_member(MockMember(456, MockPermissions(administrator=False, manage_guild=True)))  # Manage Guild
        self.guild1.add_member(MockMember(789, MockPermissions(administrator=False, manage_guild=False)))  # Normal User

        # Members for guild2
        self.guild2.add_member(MockMember(888, MockPermissions(administrator=True, manage_guild=True)))  # Owner
        self.guild2.add_member(MockMember(789, MockPermissions(administrator=True, manage_guild=True)))  # User 789 is Admin on Guild 2

        self.guild_cache[111] = self.guild1
        self.guild_cache[222] = self.guild2

    # --- 1. Service-Authentifizierung Tests ---

    def test_status_endpoint_unauthenticated(self):
        """GET /status muss ohne Authentifizierung erreichbar sein und Bot-Status liefern."""
        res = self.client.get("/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["online"])
        self.assertEqual(data["status"], "unknown")

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data, {"success": True, "api": "online"})

    def test_heartbeat_endpoint_requires_auth(self):
        res = self.client.post("/heartbeat", json={})
        self.assertEqual(res.status_code, 401)

    def test_heartbeat_endpoint_invalid_payload(self):
        res = self.client.post("/heartbeat", headers=self.auth_headers, json={"foo": "bar"})
        self.assertEqual(res.status_code, 400)

    def test_status_online_after_valid_heartbeat(self):
        payload = {
            "gateway_connected": True,
            "is_ready": True,
            "is_connecting": False,
            "last_heartbeat": "2026-01-01T00:00:00+00:00",
        }
        hb_res = self.client.post("/heartbeat", headers=self.auth_headers, json=payload)
        self.assertEqual(hb_res.status_code, 200)

        res = self.client.get("/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["online"])
        self.assertEqual(data["status"], "online")

    def test_status_offline_when_heartbeat_is_stale(self):
        payload = {
            "gateway_connected": True,
            "is_ready": True,
            "is_connecting": False,
            "last_heartbeat": "2026-01-01T00:00:00+00:00",
        }

        with patch("api.heartbeat.time.time") as time_mock:
            time_mock.return_value = 100.0
            hb_res = self.client.post("/heartbeat", headers=self.auth_headers, json=payload)
            self.assertEqual(hb_res.status_code, 200)

            time_mock.return_value = 300.0
            res = self.client.get("/status")

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["online"])
        self.assertEqual(data["status"], "offline")

    def test_missing_auth_header(self):
        """Geschützte Endpoints müssen ohne Auth-Header HTTP 401 liefern."""
        res = self.client.get("/servers?user_id=999")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Missing Authorization header", data["error"])

    def test_invalid_auth_header_format(self):
        """Ungültiges Header-Format (z. B. Basic Auth oder kein Prefix) muss 401 liefern."""
        res = self.client.get("/servers?user_id=999", headers={"Authorization": f"Basic {self.test_api_key}"})
        self.assertEqual(res.status_code, 401)

        res2 = self.client.get("/servers?user_id=999", headers={"Authorization": self.test_api_key})
        self.assertEqual(res2.status_code, 401)

    def test_wrong_api_key(self):
        """Falscher API-Schlüssel muss 401 liefern."""
        res = self.client.get("/servers?user_id=999", headers={"Authorization": "Bearer wrong_key"})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid API key", data["error"])

    def test_valid_service_auth(self):
        """Gültiger API-Schlüssel gewährt Zugriff auf geschützte Endpoints."""
        res = self.client.get("/servers?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

    def test_auth_via_dotenv_file(self):
        """Service-Authentifizierung lädt Schlüssel aus /root/Astra/.env."""
        with patch("os.path.exists", return_value=True), \
             patch("api.auth.dotenv_values", return_value={"ASTRA_INTERNAL_API_KEY": "env_file_secret_key"}):
            app = create_app(bot=self.mock_bot, guild_cache=self.guild_cache, guild_cache_lock=self.guild_cache_lock)
            client = app.test_client()
            res = client.get("/servers?user_id=999", headers={"Authorization": "Bearer env_file_secret_key"})
            self.assertEqual(res.status_code, 200)

    def test_get_expected_api_key_missing_file(self):
        """Wenn /root/Astra/.env nicht existiert, gibt get_expected_api_key None zurück."""
        with patch("os.path.exists", return_value=False):
            key = get_expected_api_key(env_path="/root/Astra/.env")
            self.assertIsNone(key)

    def test_get_expected_api_key_empty_or_missing_in_file(self):
        """Wenn Schlüssel in .env fehlt oder leer ist, gibt get_expected_api_key None zurück."""
        with patch("os.path.exists", return_value=True), \
             patch("api.auth.dotenv_values", return_value={"ASTRA_INTERNAL_API_KEY": "   "}):
            key = get_expected_api_key(env_path="/root/Astra/.env")
            self.assertIsNone(key)

        with patch("os.path.exists", return_value=True), \
             patch("api.auth.dotenv_values", return_value={}):
            key = get_expected_api_key(env_path="/root/Astra/.env")
            self.assertIsNone(key)

    def test_run_flask_aborts_when_api_key_missing(self):
        """run_flask startet Waitress nicht, wenn der API-Schlüssel fehlt oder leer ist."""
        with patch("os.path.exists", return_value=False), \
             patch("api.app.serve") as mock_serve:
            app = create_app(bot=self.mock_bot, guild_cache=self.guild_cache, guild_cache_lock=self.guild_cache_lock)
            run_flask(app, host="127.0.0.1", port=5000)
            mock_serve.assert_not_called()

    def test_run_flask_starts_when_api_key_valid(self):
        """run_flask startet Waitress, wenn ein gültiger API-Schlüssel vorhanden ist."""
        with patch("os.path.exists", return_value=True), \
             patch("api.auth.dotenv_values", return_value={"ASTRA_INTERNAL_API_KEY": "valid_key"}), \
             patch("api.app.serve") as mock_serve:
            app = create_app(bot=self.mock_bot, guild_cache=self.guild_cache, guild_cache_lock=self.guild_cache_lock)
            run_flask(app, host="127.0.0.1", port=5000)
            mock_serve.assert_called_once_with(app, host="127.0.0.1", port=5000)

    # --- 2. Benutzer-Validierung und Bot-Status Tests ---

    def test_missing_user_id(self):
        """Fehlende user_id liefert HTTP 400."""
        res = self.client.get("/servers", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Missing required parameter: user_id", data["error"])

    def test_invalid_user_id_format(self):
        """Ungültige user_id (z. B. String, negative Zahl) liefert HTTP 400."""
        res = self.client.get("/servers?user_id=abc", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)

        res2 = self.client.get("/servers?user_id=-5", headers=self.auth_headers)
        self.assertEqual(res2.status_code, 400)

    def test_bot_not_ready(self):
        """Wenn Bot nicht ready ist, müssen geschützte Endpoints HTTP 503 zurückgeben."""
        self.mock_bot.is_ready.return_value = False
        self.mock_bot.bot_ready = False
        res = self.client.get("/servers?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 503)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Bot not ready", data["error"])

    # --- 3. Benutzerautorisierung: 'Meine Server' (GET /servers) ---

    def test_get_servers_owner(self):
        """Owner sieht Server mit owner=True."""
        res = self.client.get("/servers?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        server = data["servers"][0]
        self.assertEqual(server["id"], "111")
        self.assertEqual(server["name"], "Astra Community")
        self.assertTrue(server["owner"])
        self.assertTrue(server["permissions"]["administrator"])
        self.assertTrue(server["permissions"]["manage_guild"])

    def test_get_servers_admin(self):
        """Admin sieht Server mit owner=False und administrator=True."""
        res = self.client.get("/servers?user_id=123", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 1)
        server = data["servers"][0]
        self.assertEqual(server["id"], "111")
        self.assertFalse(server["owner"])
        self.assertTrue(server["permissions"]["administrator"])

    def test_get_servers_manage_guild(self):
        """Benutzer mit Manage-Guild-Rechten sieht Server."""
        res = self.client.get("/servers?user_id=456", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 1)
        server = data["servers"][0]
        self.assertFalse(server["owner"])
        self.assertFalse(server["permissions"]["administrator"])
        self.assertTrue(server["permissions"]["manage_guild"])

    def test_get_servers_unprivileged_member(self):
        """Normaler Member auf Server 1 (789), der aber Admin auf Server 2 ist, sieht nur Server 2."""
        res = self.client.get("/servers?user_id=789", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["servers"][0]["id"], "222")

    def test_get_servers_non_member(self):
        """Benutzer ohne Mitgliedschaft oder Rechte auf irgendeinem Server erhält leere Liste."""
        res = self.client.get("/servers?user_id=999999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["servers"], [])

    def test_get_servers_empty_cache(self):
        """Wenn Guild-Cache leer ist, wird leere Liste zurückgegeben."""
        self.guild_cache.clear()
        res = self.client.get("/servers?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["servers"], [])

    def test_get_servers_member_not_in_cache_skips_api_fetch(self):
        """Bei /servers dürfen Member-Cache-Misses keinen Discord-API-Fetch auslösen."""
        self.guild1._members.pop(123, None)

        with patch("api.permissions.fetch_member_threadsafe") as fetch_mock:
            res = self.client.get("/servers?user_id=123", headers=self.auth_headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 0)
        fetch_mock.assert_not_called()

    def test_get_servers_continues_when_single_guild_errors(self):
        """Ein Fehler in einer Guild darf die Gesamtliste nicht blockieren."""
        broken_guild = MockGuild(333, "Broken", owner_id=777)
        self.guild_cache[333] = broken_guild

        with patch("api.routes.check_user_guild_permissions") as permission_mock:
            def side_effect(bot, guild, user_id, allow_api_fetch=True):
                if guild.id == 333:
                    raise RuntimeError("broken guild")
                return {"owner": True, "permissions": {"administrator": True, "manage_guild": True}, "can_manage": True} if guild.id == 111 and user_id == 999 else None

            permission_mock.side_effect = side_effect
            res = self.client.get("/servers?user_id=999", headers=self.auth_headers)

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["servers"][0]["id"], "111")

    def test_get_servers_concurrent_requests(self):
        """Gleichzeitige Dashboard-Anfragen sollen konsistent beantwortet werden."""
        app = self.app
        headers = self.auth_headers

        def do_request(user_id: int):
            with app.test_client() as client:
                response = client.get(f"/servers?user_id={user_id}", headers=headers)
                return response.status_code, response.get_json()["count"]

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(do_request, [999, 123, 456, 789]))

        self.assertEqual(results, [(200, 1), (200, 1), (200, 1), (200, 1)])

    # --- 4. Server-Details (GET /servers/<guild_id>) ---

    def test_server_detail_authorized(self):
        """Berechtigter Benutzer kann Server-Details abrufen."""
        res = self.client.get("/servers/111?user_id=123", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        server = data["server"]
        self.assertEqual(server["id"], "111")
        self.assertEqual(server["name"], "Astra Community")
        self.assertEqual(server["channelCount"], 2)
        self.assertEqual(server["roleCount"], 3)
        self.assertEqual(server["ownerId"], "999")

    def test_server_detail_forbidden(self):
        """Unberechtigter Benutzer (z. B. normaler Member ohne Rechte) erhält 403."""
        res = self.client.get("/servers/111?user_id=789", headers=self.auth_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Insufficient permissions", data["error"])

    def test_server_detail_not_found(self):
        """Nicht existierende Guild liefert 404."""
        res = self.client.get("/servers/999999?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Server not found", data["error"])

    # --- 5. Rollen abrufen (GET /servers/<guild_id>/roles) ---

    def test_server_roles_authorized(self):
        """Berechtigter Benutzer kann Rollen abrufen (@everyone wird ausgeschlossen)."""
        res = self.client.get("/servers/111/roles?user_id=123", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 2)
        role_names = [r["name"] for r in data["roles"]]
        self.assertIn("Admin", role_names)
        self.assertIn("Moderator", role_names)
        self.assertNotIn("@everyone", role_names)

    def test_server_roles_forbidden(self):
        """Unberechtigter Benutzer erhält 403 beim Rollenabruf."""
        res = self.client.get("/servers/111/roles?user_id=789", headers=self.auth_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data["success"])

    def test_server_roles_not_found(self):
        """Nicht existierende Guild liefert 404."""
        res = self.client.get("/servers/999999/roles?user_id=999", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)

    # --- 6. Fehlerbehandlungstests ---

    def test_404_not_found_endpoint(self):
        """Unbekannte Route liefert einheitliches JSON 404."""
        res = self.client.get("/nonexistent_endpoint")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data, {"success": False, "error": "Endpoint not found"})

    def test_405_method_not_allowed(self):
        """Falsche HTTP-Methode (z. B. POST auf GET /status) liefert 405 JSON."""
        res = self.client.post("/status")
        self.assertEqual(res.status_code, 405)
        data = res.get_json()
        self.assertEqual(data, {"success": False, "error": "Method not allowed"})


class PermissionsHelperTestCase(unittest.TestCase):
    def test_validate_user_id(self):
        self.assertEqual(validate_user_id("123456789012345678"), 123456789012345678)
        self.assertEqual(validate_user_id(123456789012345678), 123456789012345678)
        self.assertIsNone(validate_user_id("abc"))
        self.assertIsNone(validate_user_id("-123"))
        self.assertIsNone(validate_user_id(0))
        self.assertIsNone(validate_user_id(None))
        self.assertIsNone(validate_user_id(1 << 65))

    def test_fetch_member_threadsafe_not_found(self):
        mock_guild = MagicMock()
        mock_guild.get_member.return_value = None
        
        mock_bot = MagicMock()
        mock_bot.loop.is_closed.return_value = False

        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            mock_future = MagicMock()
            mock_future.result.side_effect = discord.NotFound(MagicMock(), "User not found")
            def close_and_return(coro, loop):
                coro.close()
                return mock_future

            mock_run.side_effect = close_and_return
            
            res = check_user_guild_permissions(mock_bot, mock_guild, 12345)
            self.assertIsNone(res)

    def test_fetch_member_threadsafe_forbidden(self):
        mock_guild = MagicMock()
        mock_guild.get_member.return_value = None
        mock_guild.id = 111
        
        mock_bot = MagicMock()
        mock_bot.loop.is_closed.return_value = False

        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            mock_future = MagicMock()
            mock_future.result.side_effect = discord.Forbidden(MagicMock(), "Forbidden")
            def close_and_return(coro, loop):
                coro.close()
                return mock_future

            mock_run.side_effect = close_and_return
            
            res = fetch_member_threadsafe(mock_bot, mock_guild, 12345)
            self.assertIsNone(res)

    def test_fetch_member_threadsafe_timeout(self):
        mock_guild = MagicMock()
        mock_guild.get_member.return_value = None
        mock_guild.id = 111
        
        mock_bot = MagicMock()
        mock_bot.loop.is_closed.return_value = False

        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            mock_future = MagicMock()
            mock_future.result.side_effect = TimeoutError("Timeout")
            def close_and_return(coro, loop):
                coro.close()
                return mock_future

            mock_run.side_effect = close_and_return
            
            res = fetch_member_threadsafe(mock_bot, mock_guild, 12345)
            self.assertIsNone(res)

    def test_check_user_guild_permissions_without_api_fetch(self):
        mock_guild = MockGuild(111, "Test", owner_id=999)
        mock_bot = MagicMock()

        with patch("api.permissions.fetch_member_threadsafe") as fetch_mock:
            res = check_user_guild_permissions(mock_bot, mock_guild, 123, allow_api_fetch=False)

        self.assertIsNone(res)
        fetch_mock.assert_not_called()

    def test_check_user_guild_permissions_event_loop_unavailable(self):
        mock_guild = MockGuild(111, "Test", owner_id=999)
        mock_guild._members = {}
        mock_bot = MagicMock()
        mock_bot.loop = None

        res = check_user_guild_permissions(mock_bot, mock_guild, 123, allow_api_fetch=True)
        self.assertIsNone(res)

    def test_check_user_guild_permissions_timeout_with_api_fetch(self):
        mock_guild = MockGuild(111, "Test", owner_id=999)
        mock_bot = MagicMock()
        mock_bot.loop.is_closed.return_value = False

        with patch("asyncio.run_coroutine_threadsafe") as mock_run:
            mock_future = MagicMock()
            mock_future.result.side_effect = TimeoutError("Timeout")
            def close_and_return(coro, loop):
                coro.close()
                return mock_future

            mock_run.side_effect = close_and_return

            res = check_user_guild_permissions(mock_bot, mock_guild, 123, allow_api_fetch=True)

        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
