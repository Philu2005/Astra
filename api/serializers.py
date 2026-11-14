import discord


def serialize_guild_summary(guild: discord.Guild, perm_info: dict | None = None) -> dict:
    """Serialisiert eine Guild für die Listenansicht (z. B. 'Meine Server')."""
    if isinstance(guild, dict):
        data = {
            "id": str(guild.get("id", "")).strip(),
            "name": guild.get("name", ""),
            "icon": guild.get("icon"),
            "memberCount": guild.get("member_count"),
        }
        if perm_info:
            data["owner"] = perm_info.get("owner", False)
            data["permissions"] = perm_info.get("permissions", {})
        return data

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
    if isinstance(guild, dict):
        channels = guild.get("channels") if isinstance(guild.get("channels"), list) else []
        roles = guild.get("roles") if isinstance(guild.get("roles"), list) else []
        data = {
            "id": str(guild.get("id", "")),
            "name": guild.get("name", ""),
            "icon": guild.get("icon"),
            "memberCount": guild.get("member_count"),
            "channelCount": len(channels),
            "roleCount": len(roles),
            "ownerId": str(guild.get("owner_id", "")),
        }
        if perm_info:
            data["owner"] = perm_info.get("owner", False)
            data["permissions"] = perm_info.get("permissions", {})
        return data

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
    if isinstance(role, dict):
        return {
            "id": str(role.get("id", "")),
            "name": role.get("name", ""),
        }

    return {
        "id": str(role.id),
        "name": role.name,
    }
