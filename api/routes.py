import logging
import time
import asyncio
from collections import deque
from functools import wraps
from threading import RLock
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request, current_app
import discord
from api.auth import require_service_auth, get_expected_api_key
from api.db import api_db
from api.permissions import validate_user_id, check_user_guild_permissions
from api.serializers import serialize_guild_summary, serialize_guild_detail, serialize_role
from api.heartbeat import heartbeat_state, derive_bot_status
from api.guild_state import guild_state_store
from cogs.ticket import api_publish_ticket_panel, api_update_ticket_panel
from utils.bot_bridge import submit_bot_task, get_bot_instance
import os
import requests
from api.moderation_services import (
    fetch_warns as svc_fetch_warns,
    fetch_all_warns as svc_fetch_all_warns,
    delete_warns as svc_delete_warns,
    delete_guild_warns as svc_delete_guild_warns,
    load_automod_config as svc_load_automod,
    save_automod_config as svc_save_automod,
    get_modlog_channel as svc_get_modlog,
    set_modlog_channel as svc_set_modlog,
)
# duplicate import removed; kept single import from utils.bot_bridge above

logger = logging.getLogger("astra.api.routes")

api_bp = Blueprint("internal_api", __name__)


def is_bot_ready() -> bool:
    """Prüft, ob ein verwertbarer Guild-Snapshot vorhanden und aktuell ist."""
    status = guild_state_store.get_sync_status()
    full_sync_ts = status.get("last_full_sync_ts")
    if full_sync_ts is None:
        return False
    max_age = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    return (time.time() - full_sync_ts) <= max_age


def get_guild_cache() -> dict:
    """Gibt den synchronisierten Guild-Cache zurück.
    Gibt eine Referenz auf das interne Dict zurück, um Deepcopy-Overhead zu vermeiden.
    Da der Store atomar ersetzt, ist dies für Lesezugriffe thread-sicher.
    """
    return guild_state_store.get_guilds_ref()


def get_guild_cache_lock():
    """Kompatibilitäts-Stub: Lock wird intern im Store verwaltet."""
    return None


def _validate_member_payload(member: dict) -> bool:
    if not isinstance(member, dict):
        return False
    member_id = validate_user_id(member.get("id"))
    if member_id is None:
        return False
    permissions = member.get("permissions")
    if not isinstance(permissions, dict):
        return False
    for key in ("administrator", "manage_guild"):
        if not isinstance(permissions.get(key), bool):
            return False
    return True


def _validate_role_payload(role: dict) -> bool:
    if not isinstance(role, dict):
        return False
    role_id = validate_user_id(role.get("id"))
    if role_id is None:
        return False
    name = role.get("name")
    if not isinstance(name, str):
        return False
    permissions = role.get("permissions")
    if permissions is not None and not isinstance(permissions, dict):
        return False
    return True


def _validate_channel_payload(channel: dict) -> bool:
    if not isinstance(channel, dict):
        return False
    channel_id = validate_user_id(channel.get("id"))
    if channel_id is None:
        return False
    if not isinstance(channel.get("name", ""), str):
        return False
    if not isinstance(channel.get("type", ""), str):
        return False
    return True


# =============================
#   Einheitliche Fehlerantwort
# =============================

def _api_error(http_status: int, code: str, message: str | None = None):
    """Erzeugt eine generische Fehlerrückgabe ohne interne Details.

    code: stabiler, maschinenlesbarer Fehlercode (z. B. 'permission_denied').
    message: optionale generische Beschreibung für Menschen.
    """
    payload = {"success": False, "code": code}
    if message:
        payload["error"] = message
    return jsonify(payload), http_status


# =============================
#   Lokaler IPC-Client (Bot)
# =============================

def _ipc_base_url() -> str:
    host = os.environ.get("ASTRA_IPC_HOST", "127.0.0.1")
    port = int(os.environ.get("ASTRA_IPC_PORT", "8765"))
    return f"http://{host}:{port}"


def _ipc_headers() -> dict:
    key = os.environ.get("ASTRA_IPC_KEY", "")
    return {"X-Astra-IPC-Key": key} if key else {}


def _ipc_request(path: str, payload: dict, timeout: float = 6.0) -> tuple[int, dict]:
    url = _ipc_base_url() + path
    try:
        r = requests.post(url, json=payload, headers=_ipc_headers(), timeout=timeout)
        data = {}
        try:
            data = r.json()
        except Exception:
            data = {"success": False, "code": "bad_gateway"}
        return r.status_code, data
    except requests.Timeout:
        return 504, {"success": False, "code": "timeout"}
    except Exception:
        logger.exception("IPC request failed: %s", url)
        return 502, {"success": False, "code": "ipc_unavailable"}


# =============================
#       Einfaches Rate-Limit
# =============================

_RL_LOCK = RLock()
_RL_BUCKETS: dict[tuple[str, str], deque] = {}


def _rate_key(scope: str) -> tuple[str, str]:
    # Schlüsselelement: API-Schlüssel aus Authorization oder Fallback IP/Anon
    auth = request.headers.get("Authorization", "").strip()
    client = auth or (request.remote_addr or "anon")
    return (scope, client)


def rate_limit(scope: str, limit: int, per_seconds: int):
    """Einfacher in‑Memory Tokenbucket (Gleitfenster) pro (scope, client).

    Hinweis: Nur für den lokalen internen Service gedacht; kein externer DoS‑Schutz.
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            now = time.time()
            key = _rate_key(scope)
            with _RL_LOCK:
                dq = _RL_BUCKETS.get(key)
                if dq is None:
                    dq = deque()
                    _RL_BUCKETS[key] = dq
                # Abgelaufene Einträge entfernen
                while dq and (now - dq[0]) > per_seconds:
                    dq.popleft()
                if len(dq) >= limit:
                    # Retry‑Hint minimal zurückgeben
                    return _api_error(429, "rate_limited", "Too many requests. Please retry later.")
                dq.append(now)
            return f(*args, **kwargs)

        return wrapper

    return decorator


# ==========================================
#      Idempotenz: Publish‑Guards/In‑Memory
# ==========================================

_PUBLISH_LOCK = RLock()
_PUBLISH_STATE: dict[tuple[int, int], dict] = {}


def _get_publish_state_key(guild_id: int, channel_id: int) -> tuple[int, int]:
    return (int(guild_id), int(channel_id))


def _is_publish_in_progress(guild_id: int, channel_id: int, window: float = 30.0) -> bool:
    key = _get_publish_state_key(guild_id, channel_id)
    now = time.time()
    with _PUBLISH_LOCK:
        st = _PUBLISH_STATE.get(key)
        if not st:
            return False
        if st.get("status") == "in_progress" and (now - st.get("ts", 0)) <= window:
            return True
    return False


def _mark_publish_state(guild_id: int, channel_id: int, status: str, payload: dict | None = None):
    key = _get_publish_state_key(guild_id, channel_id)
    with _PUBLISH_LOCK:
        _PUBLISH_STATE[key] = {"status": status, "ts": time.time(), "data": payload or {}}


async def _bot_channel_belongs_to_guild(bot, guild_id: int, channel_id: int) -> bool:
    """Harter Live‑Check über den Bot: Existiert der Channel in genau dieser Guild?"""
    if not bot:
        return False
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return False
    try:
        ch = guild.get_channel(int(channel_id))
        if ch is not None:
            return True
        # Fallback: API‑Fetch innerhalb der Guild
        _ = await guild.fetch_channel(int(channel_id))
        return True
    except Exception:
        return False


def _validate_guild_payload(guild: dict) -> bool:
    if not isinstance(guild, dict):
        return False

    guild_id = validate_user_id(guild.get("id"))
    owner_id = validate_user_id(guild.get("owner_id"))
    if guild_id is None or owner_id is None:
        return False

    if not isinstance(guild.get("name", ""), str):
        return False

    members = guild.get("members")
    roles = guild.get("roles")
    channels = guild.get("channels")

    if not isinstance(members, list) or not all(_validate_member_payload(m) for m in members):
        return False
    if not isinstance(roles, list) or not all(_validate_role_payload(r) for r in roles):
        return False
    if channels is not None and (not isinstance(channels, list) or not all(_validate_channel_payload(c) for c in channels)):
        return False

    member_count = guild.get("member_count")
    if member_count is not None and not isinstance(member_count, int):
        return False

    icon = guild.get("icon")
    if icon is not None and not isinstance(icon, str):
        return False

    return True


def _validate_stats_payload(stats: dict) -> bool:
    if not isinstance(stats, dict):
        return False
    for key in ("users", "guilds", "commands"):
        value = stats.get(key)
        if not isinstance(value, int) or value < 0:
            return False
    return True


def _validate_last_updated(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


@api_bp.route("/status", methods=["GET"])
def status():
    """Liefert den zuletzt bekannten Bot-Status auf Basis eingehender Heartbeats."""
    stale_after = float(current_app.config.get("HEARTBEAT_STALE_AFTER_SECONDS", 90))
    payload, received_ts = heartbeat_state.snapshot()
    status_data = derive_bot_status(payload, received_ts, stale_after)
    return jsonify(status_data), 200


@api_bp.route("/health", methods=["GET"]) 
def health():
    """Öffentlicher API-Healthcheck (nur Prozess-Erreichbarkeit)."""
    return jsonify(success=True, api="online"), 200


@api_bp.route("/health/live", methods=["GET"])
def health_live():
    """Liveness-Check: Prozess läuft und kann Anfragen beantworten."""
    return jsonify(success=True, status="live"), 200


@api_bp.route("/health/ready", methods=["GET"])
def health_ready():
    """Readiness-Check: API ist bereit, Anfragen entgegenzunehmen.

    Keine Datenbankprüfung – es wird lediglich geprüft, ob die
    notwendige Konfiguration (interner Service-Token) vorhanden ist,
    sodass geschützte Endpunkte benutzt werden können.
    """
    key_present = bool(get_expected_api_key())
    # Minimaler, unkritischer Output ohne Geheimnisse
    return jsonify(success=True, ready=key_present), 200


@api_bp.route("/heartbeat", methods=["POST"])
@require_service_auth
def heartbeat():
    """Nimmt einen authentifizierten Bot-Heartbeat entgegen."""
    logging.getLogger("astra.api").debug("[Heartbeat] Request eingegangen (auth ok)")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400

    required_fields = ("gateway_connected", "is_ready", "is_connecting", "last_heartbeat")
    if any(field not in payload for field in required_fields):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400

    if not isinstance(payload.get("gateway_connected"), bool):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400
    if not isinstance(payload.get("is_ready"), bool):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400
    if not isinstance(payload.get("is_connecting"), bool):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400
    if not isinstance(payload.get("last_heartbeat"), str) or not payload.get("last_heartbeat").strip():
        return jsonify(success=False, error="Invalid heartbeat payload"), 400

    shards = payload.get("shards")
    if shards is not None and not isinstance(shards, list):
        return jsonify(success=False, error="Invalid heartbeat payload"), 400

    ts = heartbeat_state.update(payload)
    logging.getLogger("astra.api").debug(
        "[Heartbeat] State aktualisiert (age=0s, ready=%s, gw=%s, connecting=%s)",
        bool(payload.get("is_ready", False)),
        bool(payload.get("gateway_connected", False)),
        bool(payload.get("is_connecting", False)),
    )
    return jsonify(success=True, sync_required=not is_bot_ready()), 200


@api_bp.route("/guild-sync", methods=["POST"])
@require_service_auth
def guild_sync():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, error="Invalid sync payload"), 400

    mode = payload.get("mode")
    stats = payload.get("stats")
    last_updated = payload.get("last_updated")

    if mode == "full_snapshot":
        guilds = payload.get("guilds")
        if not isinstance(guilds, list) or not all(_validate_guild_payload(g) for g in guilds):
            return jsonify(success=False, error="Invalid sync payload"), 400
        if not _validate_stats_payload(stats):
            return jsonify(success=False, error="Invalid sync payload"), 400
        if not _validate_last_updated(last_updated):
            return jsonify(success=False, error="Invalid sync payload"), 400

        result = guild_state_store.replace_all(guilds, stats, last_updated)
        return jsonify(success=True, mode="full_snapshot", guilds=result["guilds"]), 200

    if mode == "stats_only":
        if not _validate_stats_payload(stats):
            return jsonify(success=False, error="Invalid sync payload"), 400
        guild_state_store.update_stats(stats)
        return jsonify(success=True, mode="stats_only"), 200

    return jsonify(success=False, error="Invalid sync mode"), 400


def _get_server_data_state() -> tuple[bool, str | None]:
    status = guild_state_store.get_sync_status()
    full_sync_ts = status.get("last_full_sync_ts")
    if full_sync_ts is None:
        return False, "Guild data not synchronized"
    max_age = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    if (time.time() - full_sync_ts) > max_age:
        return False, "Guild data is stale"
    return True, None


@api_bp.route("/dashboard/stats", methods=["GET"])
@require_service_auth
def get_dashboard_stats():
    stats, last_successful_sync, full_sync_ts, stats_update_ts = guild_state_store.stats_snapshot()
    stale_after = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    
    # Statistiken sind stale, wenn weder ein Full-Snapshot noch ein Stats-Update innerhalb des Zeitfensters erfolgte
    last_any_update = max(filter(None, [full_sync_ts, stats_update_ts]), default=0)
    is_stale = last_any_update == 0 or (time.time() - last_any_update) > stale_after
    
    return jsonify(
        success=True,
        stats=stats,
        last_successful_sync=last_successful_sync,
        stale=is_stale,
    ), 200


@api_bp.route("/servers", methods=["GET"])
@require_service_auth
def get_user_servers():
    """Gibt alle Discord-Server zurück, auf denen der Bot ist und der Benutzer Verwaltungsrechte hat."""
    started = time.perf_counter()
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guilds_list = list(cache.values())

    user_servers = []
    total_guilds = len(guilds_list)
    permission_matches = 0
    errors = 0

    for guild in guilds_list:
        try:
            perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
            if perm_info is not None:
                permission_matches += 1
                user_servers.append(serialize_guild_summary(guild, perm_info))
        except Exception as e:
            errors += 1
            logger.error(f"Fehler bei Berechtigungsprüfung in einer Guild: {e}")
            continue

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "/servers Anfrage verarbeitet: guilds=%s authorized=%s errors=%s duration_ms=%s",
        total_guilds,
        permission_matches,
        errors,
        duration_ms,
    )

    return jsonify(success=True, count=len(user_servers), servers=user_servers), 200


@api_bp.route("/servers/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_server_detail(guild_id: int):
    """Gibt Detailinformationen zu einem Discord-Server zurück, falls der Benutzer berechtigt ist."""
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    return jsonify(
        success=True,
        server=serialize_guild_detail(guild, perm_info),
    ), 200


@api_bp.route("/servers/<int:guild_id>/roles", methods=["GET"])
@require_service_auth
def get_server_roles(guild_id: int):
    """Gibt die Rollen eines Servers anhand echter Discord-Daten zurück (keine Cache-Simulation)."""
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    # Über IPC beim Bot abfragen
    status_code, data = _ipc_request(
        "/ipc/resources/roles",
        {"guild_id": str(guild_id)},
        timeout=6.0,
    )
    if status_code == 200 and data.get("success"):
        return jsonify(success=True, roles=data.get("roles", [])), 200
    if status_code == 404:
        return jsonify(success=False, error="Server not found"), 404
    if status_code in (401, 502):
        return jsonify(success=False, error="Service not ready"), 503
    if status_code in (503, 504):
        return jsonify(success=False, error="Service not ready"), 503
    return jsonify(success=False, error="Failed to fetch roles"), 500


@api_bp.route("/servers/<int:guild_id>/channels", methods=["GET"])
@require_service_auth
def get_server_channels(guild_id: int):
    """Gibt alle sichtbaren Text/Voice/Thread/Stage Kanäle inkl. Typ und parent_id zurück."""
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    # Über IPC beim Bot abfragen
    status_code, data = _ipc_request(
        "/ipc/resources/channels",
        {"guild_id": str(guild_id)},
        timeout=6.0,
    )
    if status_code == 200 and data.get("success"):
        return jsonify(success=True, channels=data.get("channels", [])), 200
    if status_code == 404:
        return jsonify(success=False, error="Server not found"), 404
    if status_code in (401, 502):
        return jsonify(success=False, error="Service not ready"), 503
    if status_code in (503, 504):
        return jsonify(success=False, error="Service not ready"), 503
    return jsonify(success=False, error="Failed to fetch channels"), 500


@api_bp.route("/servers/<int:guild_id>/categories", methods=["GET"])
@require_service_auth
def get_server_categories(guild_id: int):
    """Gibt alle echten Discord-Kategorien zurück (id, name)."""
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    # Über IPC beim Bot abfragen
    status_code, data = _ipc_request(
        "/ipc/resources/categories",
        {"guild_id": str(guild_id)},
        timeout=6.0,
    )
    if status_code == 200 and data.get("success"):
        return jsonify(success=True, categories=data.get("categories", [])), 200
    if status_code == 404:
        return jsonify(success=False, error="Server not found"), 404
    if status_code in (401, 502):
        return jsonify(success=False, error="Service not ready"), 503
    if status_code in (503, 504):
        return jsonify(success=False, error="Service not ready"), 503
    return jsonify(success=False, error="Failed to fetch categories"), 500


# Neue: Server-Mitglieder (ressourcenorientiert für Dashboard)
@api_bp.route("/servers/<int:guild_id>/members", methods=["GET"])
@require_service_auth
@rate_limit(scope="server_members", limit=10, per_seconds=60)
def get_server_members(guild_id: int):
    """
    Gibt Servermitglieder für Dropdowns/Zuordnungen im Dashboard zurück.

    - Authentifiziert via Service‑Token und autorisiert gegen Guild‑Rechte des Benutzers (user_id).
    - Unterstützt Pagination über `limit` (max 200) und `after` (Snowflake; exklusive Cursor‑Pagination).
    - Liefert: id, username, display_name, avatar.
    - Wenn die Members‑Intent nicht aktiv ist oder Discord den Abruf verbietet, verständlichen Fehler zurückgeben.
    """
    server_data_ready, error = _get_server_data_state()
    if not server_data_ready:
        return jsonify(success=False, error=error), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    # Pagination-Parameter
    raw_limit = request.args.get("limit", "50")
    raw_after = request.args.get("after")  # Cursor (Snowflake) – exklusiv
    try:
        limit = int(raw_limit)
        if limit <= 0:
            limit = 50
        if limit > 200:
            limit = 200
    except Exception:
        return jsonify(success=False, error="Invalid limit"), 400

    after_obj = None
    if raw_after:
        try:
            after_obj = discord.Object(id=int(raw_after))  # type: ignore
        except Exception:
            return jsonify(success=False, error="Invalid after"), 400

    cache = get_guild_cache()
    guild_snapshot = cache.get(guild_id)
    if not guild_snapshot:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild_snapshot, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    bot = get_bot_instance()
    if bot is None:
        return jsonify(success=False, error="Service not ready"), 503

    # Prüfe Members‑Intent – ohne diese können wir regulär nicht listen.
    intents = getattr(bot, "intents", None)
    if not intents or not getattr(intents, "members", False):
        return jsonify(success=False, error="Members intent unavailable"), 503

    async def _bot_fetch_members(_bot, _guild_id: int, _limit: int, _after: discord.Object | None):
        g = _bot.get_guild(int(_guild_id))
        if g is None:
            raise RuntimeError("Guild not found")
        # REST‑Pfad: fetch_members nutzt Discord HTTP und erfordert Intents.members
        # Achtung: fetch_members liefert einen AsyncIterator
        members = []
        async for m in g.fetch_members(limit=_limit, after=_after):  # type: ignore
            members.append({
                "id": str(m.id),
                "username": m.name,
                "display_name": getattr(m, "display_name", m.name),
                "avatar": str(getattr(getattr(m, "display_avatar", None), "url", None) or ""),
            })
        # Cursor für Weiterblättern bestimmen: letzter Member als neuer after‑Wert
        next_after = members[-1]["id"] if members else None
        return {"members": members, "next_after": next_after}

    try:
        result = submit_bot_task(_bot_fetch_members(bot, guild_id, limit, after_obj), timeout=10.0)
    except discord.Forbidden:  # type: ignore
        return jsonify(success=False, error="Forbidden by Discord"), 403
    except asyncio.TimeoutError:
        return jsonify(success=False, error="Timeout"), 504
    except Exception:
        logger.exception("Failed to fetch members via bot for guild %s", guild_id)
        return jsonify(success=False, error="Failed to fetch members"), 500

    return jsonify(success=True, **result), 200


# ---------------------------------------------
# Command-Nutzungsstatistik (letzte 7 Tage)
# ---------------------------------------------

def _weekday_label_de(dt: datetime) -> str:
    # Montag=0 ... Sonntag=6 – volle deutsche Namen
    labels = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]
    return labels[dt.weekday()]


async def _fetch_command_usage_7d_global_async(pool, start_utc: datetime, end_utc: datetime):
    # Globale Aggregation nach UTC-Kalendertag (DATE(used_at)) im Intervall [start_utc, end_utc)
    # WICHTIG: kein guild_id-Filter
    sql = (
        """
        SELECT DATE(used_at) AS d, COUNT(*) AS c
        FROM command_usage
        WHERE used_at >= %s AND used_at < %s
        GROUP BY d
        ORDER BY d ASC
        """
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                sql,
                (
                    start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            rows = await cur.fetchall()
            return {str(r[0]): str(r[1]) for r in rows}


@api_bp.route("/statistics/commands", methods=["GET"])
@require_service_auth
def get_global_command_stats():
    """Liefert die tägliche Anzahl ausgeführter Commands (letzte 7 UTC-Tage) global über alle Guilds.

    Sicherheitsanforderungen:
    - Service-Auth via Bearer Token
    - Keine guild- oder user-spezifische Berechtigungsprüfung (globale Aggregation)
    - Parametrisierte SQL-Abfrage (über aiomysql) ohne guild_id-Filter
    """
    # Eigenen API‑DB‑Pool abrufen
    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    # Zeitfenster bestimmen: letzte 7 vollen Kalendertage in UTC inkl. heute
    now_utc = datetime.now(timezone.utc)
    today_utc = datetime(year=now_utc.year, month=now_utc.month, day=now_utc.day, tzinfo=timezone.utc)
    start_utc = today_utc - timedelta(days=6)
    end_utc = today_utc + timedelta(days=1)  # exklusive Obergrenze, verhindert Zukunftsdaten

    # Asynchrone DB-Abfrage im eigenen API‑Event‑Loop ausführen
    try:
        result_map = api_db.run_coro(
            _fetch_command_usage_7d_global_async(pool, start_utc, end_utc),
            timeout=float(current_app.config.get("DB_QUERY_TIMEOUT_SECONDS", 5.0)),
        )
    except FuturesTimeoutError:
        return jsonify(success=False, error="Upstream timeout while fetching statistics"), 504
    except Exception:
        # Keine DB-Fehlerdetails nach außen geben
        return jsonify(success=False, error="Failed to fetch statistics"), 500

    # Sieben Datenpunkte generieren, fehlende Tage mit 0 auffüllen
    data_points = []
    total = 0
    for i in range(7):
        day = start_utc + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        count = int(result_map.get(date_str, 0))
        total += count
        data_points.append({
            "date": date_str,
            "weekday": _weekday_label_de(day),
            "count": count,
        })

    return jsonify(
        period="7d",
        total=total,
        data=data_points,
    ), 200


# ---------------------------------------------
# Moderation: Warnungen
# ---------------------------------------------


@api_bp.route("/moderation/warns/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_guild_warns(guild_id: int):
    """Gibt alle Verwarnungen einer Guild zurück (flache Liste)."""
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        warns = api_db.run_coro(svc_fetch_all_warns(pool, guild_id), timeout=7.0)
    except Exception:
        logger.exception("Failed to fetch guild warns for guild %s", guild_id)
        return jsonify(success=False, error="Failed to fetch warns"), 500

    return jsonify(success=True, count=len(warns), warns=warns), 200


@api_bp.route("/moderation/warns/<int:guild_id>/<int:member_id>", methods=["GET"])
@require_service_auth
def get_member_warns(guild_id: int, member_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")  # aufrufender Benutzer
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        warns = api_db.run_coro(svc_fetch_warns(pool, guild_id, member_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to fetch member warns for guild %s user %s", guild_id, member_id)
        return jsonify(success=False, error="Failed to fetch warns"), 500

    return jsonify(success=True, count=len(warns), warns=warns), 200


@api_bp.route("/moderation/warns/<int:guild_id>/<int:member_id>", methods=["DELETE"])
@require_service_auth
@rate_limit(scope="warns_delete_member", limit=20, per_seconds=60)
def delete_member_warns(guild_id: int, member_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    # Entweder einzelner warn_id oder alle
    warn_id_param = request.args.get("warn_id")
    all_flag = request.args.get("all")
    warn_id_val = None
    if warn_id_param is not None:
        try:
            warn_id_val = int(str(warn_id_param).strip())
            if warn_id_val < 0:
                raise ValueError()
        except Exception:
            return jsonify(success=False, error="Invalid warn_id"), 400

    if warn_id_val is None and not (isinstance(all_flag, str) and all_flag.lower() in ("1", "true", "yes")):
        return jsonify(success=False, error="Missing warn_id or all=true"), 400

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        deleted = api_db.run_coro(svc_delete_warns(pool, guild_id, member_id, warn_id_val), timeout=5.0)
    except Exception:
        logger.exception("Failed to delete warns for guild %s user %s", guild_id, member_id)
        return jsonify(success=False, error="Failed to delete warns"), 500

    return jsonify(success=True, deleted=int(deleted)), 200


@api_bp.route("/moderation/members/lookup/<int:guild_id>", methods=["GET"])
@require_service_auth
@rate_limit(scope="member_lookup", limit=30, per_seconds=60)
def lookup_members(guild_id: int):
    """
    Löst eine Liste von User-IDs in Benutzerprofile (Name, Avatar) auf.
    Eingabe: Query-Parameter 'user_ids' (kommagetrennt).
    """
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_ids = request.args.get("user_ids", "")
    if not raw_user_ids:
        return jsonify(success=True, members={}), 200

    target_ids = []
    for rid in raw_user_ids.split(","):
        uid = validate_user_id(rid.strip())
        if uid:
            target_ids.append(uid)

    if not target_ids:
        return jsonify(success=True, members={}), 200

    # Nur die ersten 50 IDs pro Request erlauben
    target_ids = target_ids[:50]

    # Berechtigung des Aufrufers prüfen (wie bei anderen Moderations-Endpunkten)
    caller_id_raw = request.args.get("user_id") or request.headers.get("X-User-ID")
    caller_id = validate_user_id(caller_id_raw)
    if caller_id is None:
        return jsonify(success=False, error="Missing or invalid user_id"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, caller_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    # Abfrage über IPC, da Bot in eigenem Prozess läuft
    try:
        payload = {
            "guild_id": guild_id,
            "user_ids": target_ids
        }
        # _ipc_request ist in api/routes.py definiert und nutzt aiohttp-POST
        status, resp = _ipc_request("/ipc/resources/members/lookup", payload)
        
        if status == 200 and resp.get("success"):
            return jsonify(success=True, members=resp.get("members", {})), 200
        elif status == 404:
            return jsonify(success=False, error="Server not found in bot cache"), 404
        elif status == 503:
            return jsonify(success=False, error="Bot service currently unavailable"), 503
        else:
            return jsonify(success=False, error=resp.get("code") or "IPC request failed"), status or 500
            
    except Exception:
        logger.exception("Failed to lookup members via IPC for guild %s", guild_id)
        return jsonify(success=False, error="Failed to lookup members"), 500


# Serverweite Löschung aller Warns einer Guild
@api_bp.route("/moderation/warns/<int:guild_id>", methods=["DELETE"])
@require_service_auth
@rate_limit(scope="warns_delete_guild", limit=10, per_seconds=60)
def delete_guild_warns(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        deleted = api_db.run_coro(svc_delete_guild_warns(pool, guild_id), timeout=10.0)
    except Exception:
        logger.exception("Failed to delete all guild warns for guild %s", guild_id)
        return jsonify(success=False, error="Failed to delete warns"), 500

    return jsonify(success=True, deleted=int(deleted)), 200


# ---------------------------------------------
# Moderation: AutoMod
# ---------------------------------------------


@api_bp.route("/moderation/automod/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_automod_config(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        config = api_db.run_coro(svc_load_automod(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("AutoMod config loading failed for guild %s", guild_id)
        return jsonify(success=False, error="Failed to load automod config"), 500

    return jsonify(success=True, config=config), 200


@api_bp.route("/moderation/automod/<int:guild_id>", methods=["PUT"])
@require_service_auth
@rate_limit(scope="automod_put", limit=20, per_seconds=60)
def put_automod_config(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    payload = request.get_json(silent=True) or {}

    # Validierung
    rules = payload.get("rules")
    if rules is not None:
        if not isinstance(rules, list):
            return jsonify(success=False, error="Invalid rules format"), 400
        for r in rules:
            if not isinstance(r, dict):
                return jsonify(success=False, error="Invalid rule item"), 400
            try:
                _ = int(r.get("warns"))
                _a = str(r.get("action"))
                t = r.get("timeout_seconds")
                if t is not None:
                    _ = int(t)
            except Exception:
                return jsonify(success=False, error="Invalid rule values"), 400

    capslock = payload.get("capslock")
    if capslock is not None:
        if not isinstance(capslock, dict):
            return jsonify(success=False, error="Invalid capslock format"), 400
        try:
            if capslock.get("percent") is not None:
                _ = int(capslock.get("percent"))
            if capslock.get("enabled") is not None:
                _ = bool(capslock.get("enabled"))
        except Exception:
            return jsonify(success=False, error="Invalid capslock values"), 400

    blacklist = payload.get("blacklist")
    if blacklist is not None:
        if not isinstance(blacklist, dict):
            return jsonify(success=False, error="Invalid blacklist format"), 400
        if blacklist.get("words") is not None and not isinstance(blacklist.get("words"), list):
            return jsonify(success=False, error="Invalid blacklist words"), 400

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        api_db.run_coro(
            svc_save_automod(pool, guild_id, rules=rules, capslock=capslock, blacklist=blacklist),
            timeout=10.0,
        )
    except Exception:
        logger.exception("AutoMod config save failed for guild %s", guild_id)
        return jsonify(success=False, error="Failed to save automod config"), 500

    # Nach Speicherung aktuelle Konfig zurückgeben
    try:
        config = api_db.run_coro(svc_load_automod(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("AutoMod config reload after save failed for guild %s", guild_id)
        config = None

    return jsonify(success=True, config=config), 200


# ---------------------------------------------
# Moderation: Modlog
# ---------------------------------------------


@api_bp.route("/moderation/modlog/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_modlog(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        channel_id = api_db.run_coro(svc_get_modlog(pool, guild_id), timeout=5.0)
    except Exception:
        return jsonify(success=False, error="Failed to load modlog config"), 500

    return jsonify(success=True, channelId=(str(channel_id) if channel_id else None)), 200


@api_bp.route("/moderation/modlog/<int:guild_id>", methods=["PUT"]) 
@require_service_auth
@rate_limit(scope="modlog_put", limit=30, per_seconds=60)
def put_modlog(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    payload = request.get_json(silent=True) or {}
    raw_channel_id = payload.get("channel_id")
    try:
        channel_id = int(str(raw_channel_id).strip()) if raw_channel_id is not None else None
        if channel_id is not None and channel_id <= 0:
            raise ValueError()
    except Exception:
        return jsonify(success=False, error="Invalid channel_id"), 400

    # Validierung: Falls Kanalliste im Snapshot vorhanden ist, prüfen, ob Kanal zur Guild gehört
    channels = guild.get("channels") if isinstance(guild, dict) else []
    if channel_id is not None and isinstance(channels, list) and channels:
        in_guild = any(validate_user_id(c.get("id")) == channel_id for c in channels)
        if not in_guild:
            return jsonify(success=False, error="Channel does not belong to the guild"), 400

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        api_db.run_coro(svc_set_modlog(pool, guild_id, channel_id), timeout=5.0)
    except Exception:
        return jsonify(success=False, error="Failed to save modlog config"), 500

    return jsonify(success=True), 200


# ---------------------------------------------
# Ticketsystem: Konfiguration, Panels, Status, Log
# ---------------------------------------------


async def _load_ticket_config_async(pool, guild_id: int) -> dict:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT autoclose_hours, remind_minutes, reopen_hours, ping_throttle_minutes FROM ticket_config WHERE guildID=%s",
                (guild_id,),
            )
            row = await cur.fetchone()
            if not row:
                # Keine Anlage hier; Bot legt bei Bedarf an. Defaults wie im Bot:
                return {
                    "autoclose_hours": 0,
                    "remind_minutes": 0,
                    "reopen_hours": 24,
                    "ping_throttle_minutes": 0,
                }
            return {
                "autoclose_hours": int(row[0] or 0),
                "remind_minutes": int(row[1] or 0),
                "reopen_hours": int(row[2] or 0),
                "ping_throttle_minutes": int(row[3] or 0),
            }


async def _save_ticket_config_async(pool, guild_id: int, payload: dict) -> None:
    # Nur bekannte Felder zulassen
    allowed = ("autoclose_hours", "remind_minutes", "reopen_hours", "ping_throttle_minutes")
    fields = []
    vals: list[int] = []
    for k in allowed:
        if k in payload and payload[k] is not None:
            fields.append(f"{k}=%s")
            vals.append(int(payload[k]))
    if not fields:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Sicherstellen, dass Datensatz existiert
            await cur.execute("INSERT IGNORE INTO ticket_config (guildID) VALUES (%s)", (guild_id,))
            vals.append(guild_id)
            q = f"UPDATE ticket_config SET {', '.join(fields)} WHERE guildID=%s"
            await cur.execute(q, tuple(vals))


@api_bp.route("/tickets/config/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_ticket_config(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        cfg = api_db.run_coro(_load_ticket_config_async(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to load ticket config for guild %s", guild_id)
        return jsonify(success=False, error="Failed to load ticket config"), 500

    return jsonify(success=True, config=cfg), 200


@api_bp.route("/tickets/config/<int:guild_id>", methods=["PUT"]) 
@require_service_auth
@rate_limit(scope="tickets_config_put", limit=30, per_seconds=60)
def put_ticket_config(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    payload = request.get_json(silent=True) or {}
    # Validierung
    allowed = ("autoclose_hours", "remind_minutes", "reopen_hours", "ping_throttle_minutes")
    for k, v in list(payload.items()):
        if k not in allowed:
            return _api_error(400, "unsupported_field", f"Unsupported field: {k}")
        try:
            if v is not None:
                iv = int(v)
                if iv < 0:
                    return _api_error(400, "invalid_field_value", f"Invalid value for {k}")
        except Exception:
            return _api_error(400, "invalid_field_value", f"Invalid value for {k}")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    try:
        api_db.run_coro(_save_ticket_config_async(pool, guild_id, payload), timeout=7.0)
        cfg = api_db.run_coro(_load_ticket_config_async(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to save ticket config")
        return _api_error(500, "save_failed", "Failed to save ticket config")

    return jsonify(success=True, config=cfg), 200


async def _fetch_ticket_panels_async(pool, guild_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Versuche, panel_key, panelMsgID und description zu lesen
            try:
                await cur.execute(
                    "SELECT channelID, categoryID, roleID, thema, panelMsgID, description, panel_key FROM ticketsystem WHERE guildID=%s",
                    (guild_id,),
                )
                rows = await cur.fetchall()
                return [
                    {
                        "channel_id": str(r[0]),
                        "category_id": str(r[1]) if r[1] is not None else None,
                        "role_id": str(r[2]) if r[2] is not None else None,
                        "thema": r[3] or "",
                        "panel_message_id": str(r[4]) if (len(r) > 4 and r[4] is not None) else None,
                        "description": r[5] or "" if len(r) > 5 else "",
                        "panel_key": r[6] if len(r) > 6 else None,
                    }
                    for r in rows
                ]
            except Exception:
                # Fallback falls panel_key noch fehlt (während der Migration)
                try:
                    await cur.execute(
                        "SELECT channelID, categoryID, roleID, thema, panelMsgID, description FROM ticketsystem WHERE guildID=%s",
                        (guild_id,),
                    )
                    rows = await cur.fetchall()
                    return [
                        {
                            "channel_id": str(r[0]),
                            "category_id": str(r[1]) if r[1] is not None else None,
                            "role_id": str(r[2]) if r[2] is not None else None,
                            "thema": r[3] or "",
                            "panel_message_id": str(r[4]) if (len(r) > 4 and r[4] is not None) else None,
                            "description": r[5] or "" if len(r) > 5 else "",
                            "panel_key": None,
                        }
                        for r in rows
                    ]
                except Exception:
                    # Minimaler Fallback
                    await cur.execute(
                        "SELECT channelID, categoryID, roleID, thema FROM ticketsystem WHERE guildID=%s",
                        (guild_id,),
                    )
                    rows = await cur.fetchall()
                    return [
                        {
                            "channel_id": str(r[0]),
                            "category_id": str(r[1]) if r[1] is not None else None,
                            "role_id": str(r[2]) if r[2] is not None else None,
                            "thema": r[3] or "",
                            "panel_message_id": None,
                            "description": "",
                            "panel_key": None,
                        }
                        for r in rows
                    ]


@api_bp.route("/tickets/panels/<int:guild_id>", methods=["GET"]) 
@require_service_auth
def get_ticket_panels(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        panels = api_db.run_coro(_fetch_ticket_panels_async(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to load ticket panels for guild %s", guild_id)
        return jsonify(success=False, error="Failed to load panels"), 500

    # Optional: Kanal-/Kategorie-/Rollen‑Namen aus Cache anreichern
    channels = guild.get("channels") or []
    roles = guild.get("roles") or []
    ch_map = {int(c.get("id")): c for c in channels if c.get("id")}
    role_map = {int(r.get("id")): r for r in roles if r.get("id")}
    for p in panels:
        ch = ch_map.get(p["channel_id"]) if isinstance(ch_map, dict) else None
        cat = ch_map.get(p["category_id"]) if isinstance(ch_map, dict) and p.get("category_id") else None
        rr = role_map.get(p["role_id"]) if isinstance(role_map, dict) and p.get("role_id") else None
        if ch:
            p["channel_name"] = ch.get("name")
        if cat:
            p["category_name"] = cat.get("name")
        if rr:
            p["role_name"] = rr.get("name")

    return jsonify(success=True, count=len(panels), panels=panels), 200


@api_bp.route("/tickets/panels/<int:guild_id>/publish", methods=["POST"])
@require_service_auth
@rate_limit(scope="tickets_publish", limit=5, per_seconds=60)
def publish_ticket_panel(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    payload = request.get_json(silent=True) or {}

    # Dashboard-Kompatibilität: support_role_id auf role_id normalisieren
    if "role_id" not in payload and "support_role_id" in payload:
        payload["role_id"] = payload["support_role_id"]

    required_fields = (
        "channel_id",
        "category_id",
        "role_id",
        "title",
        "description"
    )
    for f in required_fields:
        if f not in payload:
            return _api_error(400, "missing_field", f"Missing field: {f}")
    try:
        channel_id = int(str(payload.get("channel_id")).strip())
        category_id = int(str(payload.get("category_id")).strip())
        role_id = int(str(payload.get("role_id")).strip())
        title = str(payload.get("title")).strip()
        description = str(payload.get("description") or "").strip()
        if not title:
            return _api_error(400, "invalid_title", "Title must not be empty")
        # Längenbegrenzung
        if len(title) > 256:
            return _api_error(400, "title_too_long", "Title exceeds 256 characters")
        if len(description) > 4000:
            return _api_error(400, "description_too_long", "Description exceeds 4000 characters")
    except Exception:
        return _api_error(400, "invalid_payload", "Invalid payload values")

    # Harte Guild-Channel-Prüfung via Bot
    bot = get_bot_instance()
    try:
        belongs = submit_bot_task(_bot_channel_belongs_to_guild(bot, guild_id, channel_id), timeout=5.0)
    except Exception:
        belongs = False
    if not belongs:
        return _api_error(400, "invalid_channel", "Channel does not belong to the guild")

    # Bereits veröffentlicht? Optional verhindern (ohne force)
    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")
    try:
        panels = api_db.run_coro(_fetch_ticket_panels_async(pool, guild_id), timeout=5.0)
        existing = next((p for p in panels if int(p["channel_id"]) == channel_id), None)
        if existing and existing.get("panel_message_id"):
            return _api_error(409, "already_published", "Panel already published")
    except Exception:
        logger.exception("Failed to check existing panel")

    # Idempotenz: parallele Anfragen verhindern
    if _is_publish_in_progress(guild_id, channel_id):
        return _api_error(409, "publish_in_progress", "Another publish is in progress")
    _mark_publish_state(guild_id, channel_id, "in_progress")
    # Primär über lokalen IPC callen (prozessübergreifend)
    status_code, data = _ipc_request(
        "/ipc/panel/publish",
        {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "category_id": str(category_id),
            "role_id": str(role_id),
            "title": title,
            "description": description,
        },
        timeout=15.0,
    )
    if status_code == 200 and data.get("success"):
        _mark_publish_state(guild_id, channel_id, "succeeded", data)
        return jsonify(
            success=True,
            status=data.get("status", "published"),
            channel_id=data.get("channel_id"),
            message_id=data.get("message_id"),
        ), 200

    # Fallback: gleiche Prozess-Bridge falls Bot hier läuft
    try:
        bot_fb = get_bot_instance()
        if bot_fb:
            result = submit_bot_task(
                api_publish_ticket_panel(
                    bot_fb,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    category_id=category_id,
                    role_id=role_id,
                    title=title,
                    description=description,
                ),
                timeout=15.0,
            )
            _mark_publish_state(guild_id, channel_id, "succeeded", result)
            return jsonify(success=True, published=result), 200
    except FuturesTimeoutError:
        _mark_publish_state(guild_id, channel_id, "failed")
        return _api_error(504, "timeout", "Publish timeout")
    except PermissionError:
        _mark_publish_state(guild_id, channel_id, "failed")
        return _api_error(403, "permission_denied", "Missing permissions for target channel")
    except Exception:
        logger.debug("Bot-bridge publish fallback failed", exc_info=True)

    _mark_publish_state(guild_id, channel_id, "failed")
    code = (data or {}).get("code", "publish_failed")
    if status_code in (400, 403, 404, 409, 410, 503, 504):
        return _api_error(status_code, code, None)
    return _api_error(500, code, None)


@api_bp.route("/tickets/panels/<int:guild_id>/<int:channel_id>/update", methods=["PUT"])
@require_service_auth
@rate_limit(scope="tickets_update", limit=10, per_seconds=60)
def update_ticket_panel(guild_id: int, channel_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    payload = request.get_json(silent=True) or {}
    title = payload.get("title")
    description = payload.get("description")
    if title is None and description is None:
        return _api_error(400, "empty_update", "No fields to update")
    if title is not None and not str(title).strip():
        return _api_error(400, "invalid_title", "Title must not be empty")
    if title is not None and len(str(title)) > 256:
        return _api_error(400, "title_too_long", "Title exceeds 256 characters")
    if description is not None and len(str(description)) > 4000:
        return _api_error(400, "description_too_long", "Description exceeds 4000 characters")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")
    try:
        panels = api_db.run_coro(_fetch_ticket_panels_async(pool, guild_id), timeout=5.0)
        existing = next((p for p in panels if int(p["channel_id"]) == channel_id), None)
        if not existing or not existing.get("panel_message_id"):
            return _api_error(404, "not_published", "No published panel found")
        message_id = int(existing.get("panel_message_id"))
    except Exception:
        logger.exception("Failed to load panel for update")
        return _api_error(500, "load_failed", "Failed to load panel")

    # Primär über IPC updaten
    status_code, data = _ipc_request(
        "/ipc/panel/update",
        {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "message_id": str(message_id),
            "title": title,
            "description": description,
        },
        timeout=15.0,
    )
    if status_code == 200 and data.get("success"):
        return jsonify(success=True, status=data.get("status", "updated")), 200

    # Fallback: Bot-Bridge (gleicher Prozess)
    try:
        result = submit_bot_task(
            api_update_ticket_panel(
                get_bot_instance(),
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                title=title,
                description=description,
            ),
            timeout=15.0,
        )
        return jsonify(success=True, updated=result), 200
    except FuturesTimeoutError:
        return _api_error(504, "timeout", "Update timeout")
    except FileNotFoundError:
        return _api_error(410, "gone", "Panel message not found")
    except Exception:
        logger.debug("Bot-bridge update fallback failed", exc_info=True)
        code = (data or {}).get("code", "update_failed")
        if status_code in (400, 403, 404, 409, 410, 503, 504):
            return _api_error(status_code, code, None)
        return _api_error(500, code, None)


@api_bp.route("/tickets/panels/<int:guild_id>/status", methods=["GET"])
@require_service_auth
def get_ticket_panel_status(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    try:
        panels = api_db.run_coro(_fetch_ticket_panels_async(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to load panels for status (guild %s)", guild_id)
        return jsonify(success=False, error="Failed to load panels"), 500

    # Basis-Status ohne Live-REST-Checks (keine zweite Discord-Implementierung)
    def _status_of(p):
        if p.get("panel_message_id"):
            return "published"
        return "not_published"

    for p in panels:
        p["status"] = _status_of(p)

    return jsonify(success=True, count=len(panels), panels=panels), 200


@api_bp.route("/tickets/panels/<int:guild_id>/<int:channel_id>/config", methods=["PUT"])
@require_service_auth
@rate_limit(scope="tickets_panel_config_put", limit=20, per_seconds=60)
def put_ticket_panel_config(guild_id: int, channel_id: int):
    """Aktualisiert Panel-Konfiguration. Unterstützt Textänderungen, Thema, Rolle, Kategorie
    sowie optionales Verschieben in einen neuen Zielkanal (Move-Flow).
    """
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    payload = request.get_json(silent=True) or {}
    # Erlaubte Felder
    allowed = {"title", "description", "thema", "role_id", "category_id", "new_channel_id"}
    for k in payload.keys():
        if k not in allowed:
            return _api_error(400, "unsupported_field", f"Unsupported field: {k}")

    title = payload.get("title")
    description = payload.get("description")
    thema = payload.get("thema")
    role_id = payload.get("role_id")
    category_id = payload.get("category_id")
    new_channel_id = payload.get("new_channel_id")

    # Text-Validierung
    if title is not None:
        if not str(title).strip():
            return _api_error(400, "invalid_title", "Title must not be empty")
        if len(str(title)) > 256:
            return _api_error(400, "title_too_long", "Title exceeds 256 characters")
    if description is not None and len(str(description)) > 4000:
        return _api_error(400, "description_too_long", "Description exceeds 4000 characters")

    # IDs parsen (optional)
    try:
        role_id_int = int(str(role_id)) if role_id is not None else None
        category_id_int = int(str(category_id)) if category_id is not None else None
        new_channel_id_int = int(str(new_channel_id)) if new_channel_id is not None else None
    except Exception:
        return _api_error(400, "invalid_payload", "Invalid id values")

    # Bestehendes Panel laden
    try:
        panels = api_db.run_coro(_fetch_ticket_panels_async(pool, guild_id), timeout=5.0)
        existing = next((p for p in panels if int(p["channel_id"]) == channel_id), None)
        if not existing:
            return _api_error(404, "panel_not_found", "Panel not found")
        existing_msg_id = existing.get("panel_message_id")
    except Exception:
        logger.exception("Failed to load panel for config update")
        return _api_error(500, "load_failed", "Failed to load panel")

    if new_channel_id_int is not None:
        # Channel-Zugehörigkeit über den IPC-Server des Bot-Prozesses prüfen.
        sc, ipc_data = _ipc_request(
            "/ipc/resources/channels",
            {"guild_id": str(guild_id)},
            timeout=8.0,
        )

        if sc != 200 or not ipc_data.get("success"):
            logger.error(
                "Ticket panel move: IPC channel validation failed "
                "(guild_id=%s, status=%s, response=%s)",
                guild_id,
                sc,
                ipc_data,
            )
            return _api_error(
                502,
                "channel_validation_unavailable",
                "Could not validate target channel",
            )

        channels = ipc_data.get("channels", [])

        belongs = any(
            str(channel.get("id")) == str(new_channel_id_int)
            for channel in channels
            if isinstance(channel, dict)
        )

        if not belongs:
            return _api_error(
                400,
                "invalid_channel",
                "Channel does not belong to the guild",
            )

    # DB-Update-Helfer für ticketsystem (thema/roleID/categoryID/channelID)
    async def _update_panel_row(pool, guild_id: int, channel_id_old: int, updates: dict):
        sets = []
        vals = []
        for k, v in updates.items():
            sets.append(f"{k}=%s")
            vals.append(v)
        vals.extend([guild_id, channel_id_old])
        q = f"UPDATE ticketsystem SET {', '.join(sets)} WHERE guildID=%s AND channelID=%s"
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q, tuple(vals))

    # 1) Falls reines Textupdate (kein Move): Bot-Update auf bestehender Message
    if new_channel_id_int is None:
        # Optional: thema in DB aktualisieren, role/category anpassen
        updates = {}
        if thema is not None:
            updates["thema"] = str(thema)
        if description is not None:
            updates["description"] = str(description)
        if role_id_int is not None:
            updates["roleID"] = role_id_int
        if category_id_int is not None:
            updates["categoryID"] = category_id_int
        if updates:
            try:
                api_db.run_coro(_update_panel_row(api_db.get_pool(), guild_id, channel_id, updates), timeout=5.0)
            except Exception:
                logger.exception("Failed to update panel row (text config)")
                return _api_error(500, "save_failed", "Failed to save panel configuration")

        # Panel-Text via IPC aktualisieren (nur wenn title/description gesetzt)
        if title is not None or description is not None:
            if not existing_msg_id:
                return _api_error(404, "not_published", "No published panel found")
            sc, data = _ipc_request(
                "/ipc/panel/update",
                {
                    "guild_id": str(guild_id),
                    "channel_id": str(channel_id),
                    "message_id": str(int(existing_msg_id)),
                    "title": title,
                    "description": description,
                },
                timeout=15.0,
            )
            if sc != 200 or not data.get("success"):
                code = (data or {}).get("code", "update_failed")
                if sc in (400, 403, 404, 409, 410, 503, 504):
                    return _api_error(sc, code, None)
                return _api_error(500, code, None)
        return jsonify(success=True, status="updated"), 200

    # 2) Move-Flow (with new_channel_id)
    if new_channel_id_int == channel_id:
        # Kein echter Move, behandle wie Text/Meta-Update
        return jsonify(success=True, status="no_move"), 200

    if not existing_msg_id:
        return _api_error(404, "not_published", "No published panel to move")

    # IPC: sichere Verschiebung (neu posten → speichern → alt löschen)
    sc, data = _ipc_request(
        "/ipc/panel/move",
        {
            "guild_id": str(guild_id),
            "old_channel_id": str(channel_id),
            "old_message_id": str(int(existing_msg_id)),
            "new_channel_id": str(new_channel_id_int),
            "category_id": str(category_id_int) if category_id_int is not None else None,
            "role_id": str(role_id_int) if role_id_int is not None else None,
            "title": title if title is not None else (thema or existing.get("thema") or "Ticket"),
            "description": description if description is not None else "",
        },
        timeout=20.0,
    )
    if sc != 200 or not data.get("success"):
        code = (data or {}).get("code", "move_failed")
        if sc in (400, 403, 404, 409, 410, 503, 504):
            return _api_error(sc, code, None)
        return _api_error(500, code, None)

    # DB: Metadaten für neue Kanalzeile aktualisieren (falls vorhanden) und alte Zeile entfernen,
    # um doppelte Einträge zu vermeiden. Die neue Zeile wurde durch Publish bereits angelegt/aktualisiert.
    try:
        # Neue Panel-Zeile ggf. mit gewünschter Meta überschreiben
        new_updates = {}
        if thema is not None:
            new_updates["thema"] = str(thema)
        if description is not None:
            new_updates["description"] = str(description)
        if role_id_int is not None:
            new_updates["roleID"] = role_id_int
        if category_id_int is not None:
            new_updates["categoryID"] = category_id_int
        if new_updates:
            # Update anhand der neuen channelID
            async def _update_new_row(pool, guild_id: int, channel_id_new: int, updates: dict):
                sets = []
                vals = []
                for k, v in updates.items():
                    sets.append(f"{k}=%s")
                    vals.append(v)
                vals.extend([guild_id, channel_id_new])
                q2 = f"UPDATE ticketsystem SET {', '.join(sets)} WHERE guildID=%s AND channelID=%s"
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(q2, tuple(vals))
            api_db.run_coro(_update_new_row(api_db.get_pool(), guild_id, new_channel_id_int, new_updates), timeout=5.0)

        # Alte Panel-Zeile entfernen
        async def _delete_old_row(pool, guild_id: int, channel_id_old: int):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM ticketsystem WHERE guildID=%s AND channelID=%s", (guild_id, channel_id_old))
        api_db.run_coro(_delete_old_row(api_db.get_pool(), guild_id, channel_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to persist panel move updates")
        # Hinweis: Neue Nachricht existiert bereits – alter Zustand bleibt; als Teilfehler melden
        return jsonify(success=True, status="moved_db_update_failed", channel_id=data.get("channel_id"), message_id=data.get("message_id")), 200

    return jsonify(success=True, status=data.get("status", "moved"), channel_id=data.get("channel_id"), message_id=data.get("message_id")), 200


@api_bp.route("/tickets/panels/<int:guild_id>/<string:panel_key>", methods=["DELETE"])
@require_service_auth
@rate_limit(scope="tickets_panel_delete", limit=10, per_seconds=60)
def delete_ticket_panel_by_key(guild_id: int, panel_key: str):
    """
    Zentraler Endpunkt zum vollständigen Löschen eines Panels via panel_key.
    Nutzt die neue Bot-Funktion 'delete_panel_completely' via IPC.
    """
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    # IPC-Request an den Bot senden
    sc, data = _ipc_request(
        "/ipc/panel/delete_complete",
        {
            "guild_id": str(guild_id),
            "panel_key": panel_key,
        },
        timeout=30.0, # Kann länger dauern, da viele Channels/Nachrichten gelöscht werden
    )
    
    if sc == 200 and (data or {}).get("success"):
        return jsonify(success=True, **data), 200
    
    if sc == 404:
        return _api_error(404, "panel_not_found", "Panel not found")
    
    if sc == 502 or (data or {}).get("code") == "ipc_unavailable":
        return _api_error(503, "service_unavailable", "Bot IPC not reachable")

    return _api_error(sc if sc != 200 else 500, (data or {}).get("code", "delete_failed"), None)


async def _fetch_open_tickets_async(pool, guild_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT channelID, msgID, opened, claimed, time FROM ticketsystem_channels WHERE guildID=%s",
                (guild_id,),
            )
            rows = await cur.fetchall()
            data = []
            for r in rows:
                opened_val = None
                try:
                    opened_val = str(r[2]) if r[2] is not None else None
                except Exception:
                    opened_val = None
                claimed_raw = r[3]
                try:
                    claimed_val = None if (claimed_raw is None or str(claimed_raw) == "Not Set") else int(claimed_raw)
                except Exception:
                    claimed_val = None
                data.append({
                    "channel_id": str(r[0]),
                    "message_id": str(r[1]),
                    "opened_by": opened_val,
                    "claimed_by": claimed_val,
                    "opened_at": r[4],  # formatierte Zeit aus Bot-Logik
                })
            return data


@api_bp.route("/tickets/status/<int:guild_id>", methods=["GET"]) 
@require_service_auth
def get_ticket_status(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        tickets = api_db.run_coro(_fetch_open_tickets_async(pool, guild_id), timeout=6.0)
    except Exception:
        logger.exception("Failed to load open tickets for guild %s", guild_id)
        return jsonify(success=False, error="Failed to load ticket status"), 500

    return jsonify(success=True, count=len(tickets), open_tickets=tickets), 200


async def _get_ticketlog_channel_async(pool, guild_id: int):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT channelID FROM ticketlog WHERE guildID=%s AND panel_key IS NULL", (guild_id,))
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None


async def _set_ticketlog_channel_async(pool, guild_id: int, channel_id: int | None):
    async with pool.acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                # Da kein Unique Key/Index existiert, nutzen wir DELETE + INSERT für panel_key IS NULL
                await cur.execute("DELETE FROM ticketlog WHERE guildID=%s AND panel_key IS NULL", (guild_id,))
                if channel_id is not None:
                    await cur.execute("INSERT INTO ticketlog (guildID, channelID, panel_key) VALUES (%s, %s, NULL)", (guild_id, channel_id))
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


@api_bp.route("/tickets/log/<int:guild_id>", methods=["GET"]) 
@require_service_auth
def get_ticketlog(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    try:
        ch_id = api_db.run_coro(_get_ticketlog_channel_async(pool, guild_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to load ticketlog")
        return _api_error(500, "load_failed", "Failed to load ticket log")

    return jsonify(success=True, channelId=(str(ch_id) if ch_id else None)), 200


@api_bp.route("/tickets/log/<int:guild_id>", methods=["PUT"]) 
@require_service_auth
@rate_limit(scope="tickets_log_put", limit=15, per_seconds=60)
def put_ticketlog(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    payload = request.get_json(silent=True) or {}
    raw_channel_id = payload.get("channel_id")
    try:
        channel_id = int(str(raw_channel_id).strip()) if raw_channel_id is not None else None
        if channel_id is not None and channel_id <= 0:
            raise ValueError()
    except Exception:
        return _api_error(400, "invalid_channel_id", "Invalid channel_id")

    # Ggf. verifizieren, dass Kanal zur Guild gehört (falls im Snapshot enthalten)
    channels = guild.get("channels") if isinstance(guild, dict) else []
    if channel_id is not None and isinstance(channels, list) and channels:
        in_guild = any(validate_user_id(c.get("id")) == channel_id for c in channels)
        if not in_guild:
            return _api_error(400, "invalid_channel", "Channel does not belong to the guild")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    try:
        api_db.run_coro(_set_ticketlog_channel_async(pool, guild_id, channel_id), timeout=5.0)
    except Exception:
        logger.exception("Failed to save ticketlog")
        return _api_error(500, "save_failed", "Failed to save ticket log")

    return jsonify(success=True), 200


@api_bp.route("/tickets/log/<int:guild_id>", methods=["DELETE"]) 
@require_service_auth
@rate_limit(scope="tickets_log_delete", limit=10, per_seconds=60)
def delete_ticketlog(guild_id: int):
    if not is_bot_ready():
        return _api_error(503, "service_unavailable", "Service not ready")

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return _api_error(400, "invalid_user_id", "Invalid user_id format")

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return _api_error(404, "server_not_found", "Server not found")

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return _api_error(403, "permission_denied", "Forbidden")

    pool = api_db.get_pool()
    if pool is None:
        return _api_error(503, "service_unavailable", "Service temporarily unavailable")

    try:
        api_db.run_coro(_set_ticketlog_channel_async(pool, guild_id, None), timeout=5.0)
    except Exception:
        logger.exception("Failed to delete ticketlog")
        return _api_error(500, "delete_failed", "Failed to delete ticket log")

    return jsonify(success=True), 200


@api_bp.route("/moderation/modlog/<int:guild_id>", methods=["DELETE"]) 
@require_service_auth
@rate_limit(scope="modlog_delete", limit=15, per_seconds=60)
def delete_modlog(guild_id: int):
    if not is_bot_ready():
        return jsonify(success=False, error="Service not ready"), 503

    raw_user_id = request.args.get("user_id")
    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    cache = get_guild_cache()
    guild = cache.get(guild_id)
    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(None, guild, user_id, allow_api_fetch=False)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    pool = api_db.get_pool()
    if pool is None:
        return jsonify(success=False, error="Service temporarily unavailable"), 503

    try:
        api_db.run_coro(svc_set_modlog(pool, guild_id, None), timeout=5.0)
    except Exception:
        return jsonify(success=False, error="Failed to delete modlog config"), 500

    return jsonify(success=True), 200
