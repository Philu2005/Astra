import logging
import time
import asyncio
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request, current_app
from api.auth import require_service_auth, get_expected_api_key
from api.db import api_db
from api.permissions import validate_user_id, check_user_guild_permissions
from api.serializers import serialize_guild_summary, serialize_guild_detail, serialize_role
from api.heartbeat import heartbeat_state, derive_bot_status
from api.guild_state import guild_state_store
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
            return {str(r[0]): int(r[1]) for r in rows}


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


# Serverweite Löschung aller Warns einer Guild
@api_bp.route("/moderation/warns/<int:guild_id>", methods=["DELETE"])
@require_service_auth
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


@api_bp.route("/moderation/modlog/<int:guild_id>", methods=["DELETE"])
@require_service_auth
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
