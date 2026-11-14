import logging
import time
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from api.auth import require_service_auth, get_expected_api_key
from api.permissions import validate_user_id, check_user_guild_permissions
from api.serializers import serialize_guild_summary, serialize_guild_detail, serialize_role
from api.heartbeat import heartbeat_state, derive_bot_status
from api.guild_state import guild_state_store

logger = logging.getLogger("astra.api.routes")

api_bp = Blueprint("internal_api", __name__)


def is_bot_ready() -> bool:
    """Prüft, ob ein verwertbarer Guild-Snapshot vorhanden und aktuell ist."""
    _, full_sync_ts, _ = guild_state_store.snapshot()
    if full_sync_ts is None:
        return False
    max_age = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    return (time.time() - full_sync_ts) <= max_age


def get_guild_cache() -> dict:
    """Gibt den synchronisierten Guild-Cache zurück."""
    guilds, _, _ = guild_state_store.snapshot()
    return guilds


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

    heartbeat_state.update(payload)
    return jsonify(success=True), 200


@api_bp.route("/guild-sync", methods=["POST"])
@require_service_auth
def guild_sync():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, error="Invalid sync payload"), 400

    mode = payload.get("mode")
    if mode != "full_snapshot":
        return jsonify(success=False, error="Invalid sync payload"), 400

    guilds = payload.get("guilds")
    stats = payload.get("stats")
    last_updated = payload.get("last_updated")

    if not isinstance(guilds, list) or not all(_validate_guild_payload(g) for g in guilds):
        return jsonify(success=False, error="Invalid sync payload"), 400
    if not _validate_stats_payload(stats):
        return jsonify(success=False, error="Invalid sync payload"), 400
    if not _validate_last_updated(last_updated):
        return jsonify(success=False, error="Invalid sync payload"), 400

    result = guild_state_store.replace_all(guilds, stats, last_updated)
    return jsonify(success=True, mode="full_snapshot", guilds=result["guilds"]), 200


def _get_server_data_state() -> tuple[bool, str | None]:
    _, full_sync_ts, _ = guild_state_store.snapshot()
    if full_sync_ts is None:
        return False, "Guild data not synchronized"
    max_age = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    if (time.time() - full_sync_ts) > max_age:
        return False, "Guild data is stale"
    return True, None


@api_bp.route("/dashboard/stats", methods=["GET"])
@require_service_auth
def get_dashboard_stats():
    stats, last_successful_sync, full_sync_ts = guild_state_store.stats_snapshot()
    stale_after = float(current_app.config.get("GUILD_SNAPSHOT_STALE_AFTER_SECONDS", 120))
    is_stale = full_sync_ts is None or (time.time() - full_sync_ts) > stale_after
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
    owner_hits = 0
    cache_member_hits = 0
    permission_matches = 0
    errors = 0

    for guild in guilds_list:
        try:
            if validate_user_id(guild.get("owner_id")) == user_id:
                owner_hits += 1
            elif any(validate_user_id(m.get("id")) == user_id for m in guild.get("members", [])):
                cache_member_hits += 1

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
        "/servers Anfrage verarbeitet: guilds=%s owner_cache_hits=%s member_cache_hits=%s authorized=%s errors=%s duration_ms=%s",
        total_guilds,
        owner_hits,
        cache_member_hits,
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
    """Gibt die Rollen eines Servers zurück, falls der Benutzer berechtigt ist."""
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

    guild_roles = guild.get("roles", [])
    roles = [
        serialize_role(role)
        for role in guild_roles
        if role.get("name", "") != "@everyone"
    ]

    return jsonify(success=True, count=len(roles), roles=roles), 200
