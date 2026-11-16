import logging
from typing import Any, Iterable


logger = logging.getLogger("astra.api.moderation_services")


# -----------------------------
# WARNINGS (warns)
# -----------------------------


async def fetch_warns(pool, guild_id: int, user_id: int) -> list[dict]:
    """Liest Verwarnungen eines Mitglieds aus der bestehenden Tabelle `warns`.

    Schema laut Bestand:
      warns(guildID BIGINT, userID BIGINT, reason TEXT, warnID INT, PRIMARY KEY (guildID, userID, warnID))
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT warnID, reason FROM warns WHERE guildID=%s AND userID=%s ORDER BY warnID ASC",
                (guild_id, user_id),
            )
            rows = await cur.fetchall() or []
            return [
                {"warnId": int(warn_id), "reason": (reason or "")} for (warn_id, reason) in rows
            ]


async def delete_warns(pool, guild_id: int, user_id: int, warn_id: int | None = None) -> int:
    """Entfernt eine spezifische Verwarnung (warn_id) oder alle eines Users in einer Guild.
    Gibt die Anzahl gelöschter Reihen zurück.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Transaktion für Konsistenz
            try:
                await conn.begin()
                if warn_id is None:
                    await cur.execute(
                        "DELETE FROM warns WHERE guildID=%s AND userID=%s",
                        (guild_id, user_id),
                    )
                else:
                    await cur.execute(
                        "DELETE FROM warns WHERE guildID=%s AND userID=%s AND warnID=%s",
                        (guild_id, user_id, warn_id),
                    )
                affected = cur.rowcount or 0
                await conn.commit()
                return int(affected)
            except Exception:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise


# -----------------------------
# AUTOMOD KONFIGURATION
# -----------------------------


async def load_automod_config(pool, guild_id: int) -> dict:
    """Lädt die vollständige AutoMod-Konfiguration aus den bestehenden Tabellen.

    Tabellen gemäß Bestandscode:
      - automod(guildID, warns, action, timeout_seconds)
      - capslock(guildID, percent[, status])  -- 'status' wird defensiv gelesen
      - blacklist_settings(serverID, status)
      - blacklist_words(serverID, word)
    """
    rules: list[dict[str, Any]] = []
    caps_percent: int | None = None
    caps_enabled: bool = False
    bl_enabled: bool = False
    bl_words: list[str] = []

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Warn-Regeln
            await cur.execute(
                "SELECT warns, action, timeout_seconds FROM automod WHERE guildID=%s ORDER BY warns ASC",
                (guild_id,),
            )
            rules = [
                {"warns": int(w), "action": str(a), "timeout_seconds": (int(t) if t is not None else None)}
                for (w, a, t) in (await cur.fetchall() or [])
            ]

            # Capslock
            try:
                await cur.execute(
                    "SELECT percent, status FROM capslock WHERE guildID=%s",
                    (guild_id,),
                )
                row = await cur.fetchone()
                if row:
                    caps_percent = int(row[0]) if row[0] is not None else None
                    caps_enabled = bool(row[1]) if len(row) > 1 else False
            except Exception:
                # Fallback auf alte Struktur ohne 'status'
                await cur.execute(
                    "SELECT percent FROM capslock WHERE guildID=%s",
                    (guild_id,),
                )
                row = await cur.fetchone()
                if row:
                    caps_percent = int(row[0]) if row[0] is not None else None
                    caps_enabled = False

            # Blacklist Settings
            try:
                await cur.execute(
                    "SELECT status FROM blacklist_settings WHERE serverID=%s",
                    (guild_id,),
                )
                row = await cur.fetchone()
                bl_enabled = bool(row[0]) if row else False
            except Exception:
                bl_enabled = False

            # Blacklist Wörter
            try:
                await cur.execute(
                    "SELECT word FROM blacklist_words WHERE serverID=%s",
                    (guild_id,),
                )
                bl_words = [str(w or "") for (w,) in (await cur.fetchall() or [])]
            except Exception:
                bl_words = []

    return {
        "rules": rules,
        "capslock": {"percent": caps_percent, "enabled": caps_enabled},
        "blacklist": {"enabled": bl_enabled, "words": bl_words},
    }


async def save_automod_config(
    pool,
    guild_id: int,
    *,
    rules: Iterable[dict] | None,
    capslock: dict | None,
    blacklist: dict | None,
) -> None:
    """Speichert die AutoMod-Konfiguration transaktional.

    - Regeln werden für die Guild vollständig ersetzt (DELETE + INSERT).
    - Capslock wird upserted (defensiv auch ohne 'status').
    - Blacklist-Status wird upserted, Wörter werden vollständig ersetzt.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()

                # Regeln
                if rules is not None:
                    await cur.execute("DELETE FROM automod WHERE guildID=%s", (guild_id,))
                    for r in rules:
                        w = int(r.get("warns"))
                        a = str(r.get("action"))
                        t = r.get("timeout_seconds")
                        await cur.execute(
                            "INSERT INTO automod (guildID, warns, action, timeout_seconds) VALUES (%s, %s, %s, %s)",
                            (guild_id, w, a, (int(t) if t is not None else None)),
                        )

                # Capslock
                if capslock is not None:
                    percent = capslock.get("percent")
                    enabled = capslock.get("enabled")
                    # Prüfe, ob Spalte 'status' existiert – wir versuchen erst, mit status zu upserten
                    try:
                        # Lösche existierenden Eintrag und schreibe neu (kompatibler als ON DUPLICATE)
                        await cur.execute("DELETE FROM capslock WHERE guildID=%s", (guild_id,))
                        await cur.execute(
                            "INSERT INTO capslock (guildID, percent, status) VALUES (%s, %s, %s)",
                            (guild_id, int(percent), 1 if enabled else 0),
                        )
                    except Exception:
                        # Fallback ohne 'status'
                        await cur.execute("DELETE FROM capslock WHERE guildID=%s", (guild_id,))
                        await cur.execute(
                            "INSERT INTO capslock (guildID, percent) VALUES (%s, %s)",
                            (guild_id, int(percent)),
                        )

                # Blacklist
                if blacklist is not None:
                    enabled = 1 if bool(blacklist.get("enabled", False)) else 0
                    words = [str(w).strip() for w in (blacklist.get("words") or []) if str(w).strip()]
                    # Einstellungen upserten
                    try:
                        await cur.execute("DELETE FROM blacklist_settings WHERE serverID=%s", (guild_id,))
                        await cur.execute(
                            "INSERT INTO blacklist_settings (serverID, status) VALUES (%s, %s)",
                            (guild_id, enabled),
                        )
                    except Exception:
                        # Falls Tabelle nicht existiert, ignorieren – Wörter werden dennoch gespeichert, wenn möglich
                        pass

                    # Wörter ersetzen
                    try:
                        await cur.execute("DELETE FROM blacklist_words WHERE serverID=%s", (guild_id,))
                        for w in words:
                            await cur.execute(
                                "INSERT INTO blacklist_words (serverID, word) VALUES (%s, %s)",
                                (guild_id, w),
                            )
                    except Exception:
                        # Tabelle evtl. nicht vorhanden – stiller Fallback
                        pass

                await conn.commit()
            except Exception:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise


# -----------------------------
# MODLOG KONFIGURATION
# -----------------------------


async def get_modlog_channel(pool, guild_id: int) -> int | None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT channelID FROM modlog WHERE serverID=%s LIMIT 1",
                (guild_id,),
            )
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None


async def set_modlog_channel(pool, guild_id: int, channel_id: int | None) -> None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.begin()
                await cur.execute("DELETE FROM modlog WHERE serverID=%s", (guild_id,))
                if channel_id is not None:
                    await cur.execute(
                        "INSERT INTO modlog (serverID, channelID) VALUES (%s, %s)",
                        (guild_id, channel_id),
                    )
                await conn.commit()
            except Exception:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise
