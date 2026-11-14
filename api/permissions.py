import asyncio
import logging
import discord

logger = logging.getLogger("astra.api.permissions")


def _build_manage_permissions(owner: bool, administrator: bool, manage_guild: bool) -> dict:
    return {
        "owner": owner,
        "permissions": {
            "administrator": administrator,
            "manage_guild": manage_guild,
        },
        "can_manage": True,
    }


def validate_user_id(raw_id: str | int | None) -> int | None:
    """Validiert eine Discord-User-ID (Snowflake).
    
    Gibt die Integer-ID zurück oder None bei ungültigem Format.
    """
    if raw_id is None:
        return None
    try:
        user_id = int(str(raw_id).strip())
        # Discord Snowflakes sind positive Ganzzahlen (typisch 17-20 Stellen)
        if user_id <= 0 or user_id > (1 << 64) - 1:
            return None
        return user_id
    except (ValueError, TypeError):
        return None


def fetch_member_threadsafe(bot, guild: discord.Guild, user_id: int, timeout: float = 5.0) -> discord.Member | None:
    """Ruft ein Guild-Mitglied thread-sicher über den Discord-Event-Loop ab.
    
    Prüft zuerst den lokalen Cache von discord.py. Falls nicht vorhanden,
    wird ein API-Fetch über den Bot-Loop durchgeführt.
    """
    # 1. Zunächst Cache prüfen
    member = guild.get_member(user_id)
    if member is not None:
        return member

    # 2. Prüfen, ob Event-Loop verfügbar ist
    if not bot or not getattr(bot, "loop", None) or bot.loop.is_closed():
        return None

    # 3. Thread-sicherer Aufruf im Event-Loop des Bots
    try:
        coro = guild.fetch_member(user_id)
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        return future.result(timeout=timeout)
    except discord.NotFound:
        # Benutzer ist nicht auf dem Server
        return None
    except discord.Forbidden:
        logger.warning(f"Keine Berechtigung zum Abrufen von Mitglied {user_id} auf Guild {guild.id}")
        return None
    except discord.HTTPException as e:
        logger.warning(f"Discord-API-Fehler beim Abruf von Mitglied {user_id} auf Guild {guild.id}: {e}")
        return None
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning(f"Timeout beim Abruf von Mitglied {user_id} auf Guild {guild.id}")
        return None
    except Exception as e:
        logger.warning(f"Unerwarteter Fehler beim Abruf von Mitglied {user_id}: {e}")
        return None


def check_user_guild_permissions(bot, guild: discord.Guild, user_id: int, allow_api_fetch: bool = True) -> dict | None:
    """Prüft, ob der Benutzer Mitglied der Guild ist und Verwaltungsrechte besitzt.
    
    Berücksichtigte Berechtigungen:
    - Serverbesitzer (Owner)
    - Administrator
    - Manage Guild (Server verwalten)
    
    Gibt ein Dict mit Berechtigungsinformationen zurück, wenn der Benutzer berechtigt ist,
    oder None, wenn der Benutzer kein Mitglied ist oder keine ausreichenden Rechte besitzt.
    """
    if guild is None or not user_id:
        return None

    if isinstance(guild, dict):
        return _check_user_serialized_guild_permissions(guild, user_id)

    # Schnellprüfung: Ist der Benutzer der Serverbesitzer?
    if getattr(guild, "owner_id", None) == user_id:
        return _build_manage_permissions(owner=True, administrator=True, manage_guild=True)

    # Mitglied ermitteln
    member = guild.get_member(user_id)
    if member is None and allow_api_fetch:
        member = fetch_member_threadsafe(bot, guild, user_id)

    if member is None:
        return None

    # Besitzer-Check über Member-Objekt (Fallback)
    if getattr(guild, "owner_id", None) == member.id:
        return _build_manage_permissions(owner=True, administrator=True, manage_guild=True)

    # Guild-Berechtigungen auswerten
    perms = getattr(member, "guild_permissions", None)
    admin = bool(perms.administrator) if perms else False
    manage_guild = bool(perms.manage_guild) if perms else False

    if admin or manage_guild:
        return _build_manage_permissions(owner=False, administrator=admin, manage_guild=manage_guild)

    return None


def _check_user_serialized_guild_permissions(guild_data: dict, user_id: int) -> dict | None:
    owner_id = validate_user_id(guild_data.get("owner_id"))
    if owner_id == user_id:
        return _build_manage_permissions(owner=True, administrator=True, manage_guild=True)

    members = guild_data.get("members")
    if not isinstance(members, list):
        return None

    for member in members:
        if not isinstance(member, dict):
            continue

        member_id = validate_user_id(member.get("id"))
        if member_id != user_id:
            continue

        perms = member.get("permissions") if isinstance(member.get("permissions"), dict) else {}
        admin = bool(perms.get("administrator", False))
        manage_guild = bool(perms.get("manage_guild", False))
        if admin or manage_guild:
            return _build_manage_permissions(owner=False, administrator=admin, manage_guild=manage_guild)
        return None

    return None
