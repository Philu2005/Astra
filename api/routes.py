import logging
from flask import Blueprint, jsonify, request, current_app
from api.auth import require_service_auth
from api.permissions import validate_user_id, check_user_guild_permissions
from api.serializers import serialize_guild_summary, serialize_guild_detail, serialize_role

logger = logging.getLogger("astra.api.routes")

api_bp = Blueprint("internal_api", __name__)


def is_bot_ready() -> bool:
    """Prüft, ob die Bot-Instanz bereit ist."""
    bot = current_app.config.get("DISCORD_BOT")
    if bot is None:
        return False
    if hasattr(bot, "is_ready") and not bot.is_ready():
        return False
    if hasattr(bot, "bot_ready") and not bot.bot_ready:
        return False
    return True


def get_guild_cache() -> dict:
    """Gibt den Guild-Cache zurück."""
    return current_app.config.get("GUILD_CACHE", {})


def get_guild_cache_lock():
    """Gibt den Guild-Cache-Lock zurück."""
    return current_app.config.get("GUILD_CACHE_LOCK")


@api_bp.route("/status", methods=["GET"])
def status():
    """Öffentlicher, minimaler Healthcheck-Endpoint.
    
    Gibt bewusst keine internen Systemdaten, Secrets oder Guild-Infos preis.
    """
    return jsonify(online=True), 200


@api_bp.route("/servers", methods=["GET"])
@require_service_auth
def get_user_servers():
    """Gibt alle Discord-Server zurück, auf denen der Bot ist und der Benutzer Verwaltungsrechte hat."""
    if not is_bot_ready():
        return jsonify(success=False, error="Bot not ready"), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    bot = current_app.config.get("DISCORD_BOT")
    cache = get_guild_cache()
    lock = get_guild_cache_lock()

    # Snapshot der Guilds unter Lock ziehen, um Lock nicht während Berechtigungsabfragen zu blockieren
    if lock:
        with lock:
            guilds_list = list(cache.values())
    else:
        guilds_list = list(cache.values())

    user_servers = []
    for guild in guilds_list:
        try:
            perm_info = check_user_guild_permissions(bot, guild, user_id)
            if perm_info is not None:
                user_servers.append(serialize_guild_summary(guild, perm_info))
        except Exception as e:
            logger.error(f"Fehler bei Berechtigungsprüfung für Guild {guild.id}: {e}")
            continue

    return jsonify(success=True, count=len(user_servers), servers=user_servers), 200


@api_bp.route("/servers/<int:guild_id>", methods=["GET"])
@require_service_auth
def get_server_detail(guild_id: int):
    """Gibt Detailinformationen zu einem Discord-Server zurück, falls der Benutzer berechtigt ist."""
    if not is_bot_ready():
        return jsonify(success=False, error="Bot not ready"), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    bot = current_app.config.get("DISCORD_BOT")
    cache = get_guild_cache()
    lock = get_guild_cache_lock()

    guild = None
    if lock:
        with lock:
            guild = cache.get(guild_id)
    else:
        guild = cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(bot, guild, user_id)
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
    if not is_bot_ready():
        return jsonify(success=False, error="Bot not ready"), 503

    raw_user_id = request.args.get("user_id") or request.headers.get("X-User-ID")
    if not raw_user_id:
        return jsonify(success=False, error="Missing required parameter: user_id"), 400

    user_id = validate_user_id(raw_user_id)
    if user_id is None:
        return jsonify(success=False, error="Invalid user_id format"), 400

    bot = current_app.config.get("DISCORD_BOT")
    cache = get_guild_cache()
    lock = get_guild_cache_lock()

    guild = None
    if lock:
        with lock:
            guild = cache.get(guild_id)
    else:
        guild = cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    perm_info = check_user_guild_permissions(bot, guild, user_id)
    if perm_info is None:
        return jsonify(success=False, error="Forbidden: Insufficient permissions"), 403

    guild_roles = getattr(guild, "roles", [])
    roles = [
        serialize_role(role)
        for role in guild_roles
        if getattr(role, "name", "") != "@everyone"
    ]

    return jsonify(success=True, count=len(roles), roles=roles), 200
