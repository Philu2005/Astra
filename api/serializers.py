import discord


def serialize_guild_summary(guild: discord.Guild, perm_info: dict | None = None) -> dict:
    """Serialisiert eine Guild für die Listenansicht (z. B. 'Meine Server')."""
    icon_key = guild.icon.key if getattr(guild, "icon", None) else None
    data = {
        "id": str(guild.id).strip(),
        "name": guild.name,
        "icon": icon_key,
        "memberCount": getattr(guild, "member_count", None),
    }
    if perm_info:
        data["owner"] = perm_info.get("owner", False)
        data["permissions"] = perm_info.get("permissions", {})
    return data


def serialize_guild_detail(guild: discord.Guild, perm_info: dict | None = None) -> dict:
    """Serialisiert ausführliche Informationen einer Guild."""
    icon_key = guild.icon.key if getattr(guild, "icon", None) else None
    channels = getattr(guild, "channels", [])
    roles = getattr(guild, "roles", [])
    owner_id = getattr(guild, "owner_id", "")

    data = {
        "id": str(guild.id),
        "name": guild.name,
        "icon": icon_key,
        "memberCount": getattr(guild, "member_count", None),
        "channelCount": len(channels),
        "roleCount": len(roles),
        "ownerId": str(owner_id),
    }
    if perm_info:
        data["owner"] = perm_info.get("owner", False)
        data["permissions"] = perm_info.get("permissions", {})
    return data


def serialize_role(role: discord.Role) -> dict:
    """Serialisiert eine Discord-Rolle."""
    return {
        "id": str(role.id),
        "name": role.name,
    }
