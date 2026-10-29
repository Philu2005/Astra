# geburtstag_system.py — exakt HH:mm:00, Multi-{mention}, schlichtes Embed, Alias-UPSERT, Modal (Embed ja/nein), Status (AN/AUS)
import asyncio
import logging
from typing import Optional, Tuple, List, Dict, Literal

import discord
from discord.ext import commands
from discord import app_commands

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STD_MSG = "Lasst uns {mention} zum Geburtstag gratulieren! 🎉"
FALLBACK_TZ = "Europe/Berlin"

# Kurze, kuratierte TZ-Liste (D-A-CH + ein paar EU/US)
ALLOWED_TZS: List[str] = [
    "Europe/Berlin", "Europe/Vienna", "Europe/Zurich",
    "Europe/Luxembourg", "Europe/Brussels", "Europe/Amsterdam",
    "Europe/Paris", "Europe/Madrid", "Europe/Rome", "Europe/London",
    "America/New_York",
]

# ================= Utils =================

def _parse_hhmm(s: str) -> Optional[Tuple[int, int]]:
    try:
        s = s.strip()
        if len(s) != 5 or s[2] != ":":
            return None
        hh = int(s[:2]); mm = int(s[3:])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
        return None
    except Exception:
        return None

def _safe_tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or FALLBACK_TZ)
    except Exception:
        return ZoneInfo(FALLBACK_TZ)

def _calc_next_epoch(day: int, month: int, tz: ZoneInfo, hour: int, minute: int, ref: Optional[datetime] = None) -> int:
    now = (ref or datetime.now(tz)).astimezone(tz)
    y = now.year
    hour = max(0, min(23, int(hour))); minute = max(0, min(59, int(minute)))
    while True:
        try:
            cand = datetime(y, month, day, hour, minute, tzinfo=tz)
            if cand <= now:
                y += 1
                continue
            return int(cand.timestamp())
        except ValueError:
            y += 1  # z. B. 29.02.

def _format_mentions_list(members: List[discord.Member]) -> str:
    # "@A", "@A und @B", "@A, @B und @C"
    if not members:
        return ""
    parts = [m.mention for m in members]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" und {parts[-1]}"

# ================= Cog: Versandticker (pro Guild) =================

class Birthday(commands.Cog):
    """
    Checkt exakt zum Minutenbeginn (HH:mm:00) fällige Geburtstage (next_epoch) und
    postet in den je Guild konfigurierten Channel — gemäß deren HH:mm, Zeitzone & Embedding.
    Tabellen: birthdays_guild, birthday_settings (inkl. enabled)
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task = asyncio.create_task(self._ticker())

    def cog_unload(self):
        self._task.cancel()

    async def _load_settings(self) -> Dict[int, tuple]:
        """
        Liefert Einstellungen je Guild:
        { guild_id: (channel_id, tpl, hour, minute, tz_name, use_embed, enabled) }
        """
        settings: Dict[int, tuple] = {}
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT guild_id, COALESCE(channel_id,0), "
                    "COALESCE(message_template,''), COALESCE(send_hour,9), COALESCE(send_minute,0), "
                    "COALESCE(tz_name,%s), COALESCE(use_embed,1), COALESCE(enabled,1) "
                    "FROM birthday_settings",
                    (FALLBACK_TZ,)
                )
                for g_id, ch_id, tpl, hr, mn, tz_name, use_embed, enabled in await cur.fetchall():
                    settings[int(g_id)] = (int(ch_id), tpl or "", int(hr), int(mn), tz_name or FALLBACK_TZ, int(use_embed), int(enabled))
        return settings

    async def _ticker(self):
        await self.bot.wait_until_ready()

        def next_minute_utc(from_dt: Optional[datetime] = None) -> datetime:
            now = (from_dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
            return (now.replace(second=0, microsecond=0) + timedelta(minutes=1))

        wake = next_minute_utc()
        while not self.bot.is_closed():
            try:
                # exakt zum Minutenbeginn
                await discord.utils.sleep_until(wake)
                current_ts = int(wake.timestamp())

                settings = await self._load_settings()
                if not settings:
                    wake = next_minute_utc(wake); continue

                # Alle Einträge, die JETZT fällig sind
                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT guild_id, user_id, birth_str, day, month, year, next_epoch "
                            "FROM birthdays_guild WHERE next_epoch=%s",
                            (current_ts,)
                        )
                        rows = await cur.fetchall()

                # Gruppieren je Guild (gleichzeitige Geburtstage zusammen ausgeben)
                grouped: Dict[int, List[tuple]] = {}
                for g_id, user_id, birth_str, d, m, y, ne in rows:
                    grouped.setdefault(int(g_id), []).append((int(user_id), birth_str, int(d), int(m), int(y)))

                for g_id, items in grouped.items():
                    try:
                        ch_id, tpl, hr, mn, tz_name, use_embed, enabled = settings.get(
                            g_id, (0, "", 9, 0, FALLBACK_TZ, 1, 1)
                        )

                        tz = _safe_tz(tz_name)
                        # Guild deaktiviert? Überspringen + nur next_epoch neu planen.
                        if int(enabled) == 0:
                            for user_id, _birth_str, d, m, y in items:
                                new_epoch = _calc_next_epoch(d, m, tz, hr, mn)
                                async with self.bot.pool.acquire() as conn:
                                    async with conn.cursor() as cur:
                                        await cur.execute(
                                            "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                                            (new_epoch, g_id, user_id)
                                        )
                            continue

                        guild = self.bot.get_guild(g_id)
                        if not guild or not ch_id:
                            # Bot ist nicht mehr auf dem Server oder kein Channel konfiguriert -> sauber next_epoch neu planen
                            for user_id, _birth_str, d, m, y in items:
                                new_epoch = _calc_next_epoch(d, m, tz, hr, mn)
                                async with self.bot.pool.acquire() as conn:
                                    async with conn.cursor() as cur:
                                        await cur.execute(
                                            "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                                            (new_epoch, g_id, user_id)
                                        )
                            continue

                        channel = guild.get_channel(int(ch_id))
                        if channel is None:
                            try:
                                channel = await guild.fetch_channel(int(ch_id))
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                channel = None

                        if not isinstance(channel, discord.TextChannel):
                            for user_id, _birth_str, d, m, y in items:
                                new_epoch = _calc_next_epoch(d, m, tz, hr, mn)
                                async with self.bot.pool.acquire() as conn:
                                    async with conn.cursor() as cur:
                                        await cur.execute(
                                            "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                                            (new_epoch, g_id, user_id)
                                        )
                            continue

                        # Mitglieder sammeln, die (noch) auf dem Server sind
                        members: List[discord.Member] = []
                        any_birth_str = None
                        for user_id, birth_str, d, m, y in items:
                            mem = guild.get_member(user_id)
                            if mem:
                                members.append(mem)
                                any_birth_str = any_birth_str or birth_str
                        if not members:
                            # Trotzdem next_epoch neu planen
                            for user_id, _birth_str, d, m, y in items:
                                new_epoch = _calc_next_epoch(d, m, tz, hr, mn)
                                async with self.bot.pool.acquire() as conn:
                                    async with conn.cursor() as cur:
                                        await cur.execute(
                                            "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                                            (new_epoch, g_id, user_id)
                                        )
                            continue

                        # Template befüllen
                        mentions_str = _format_mentions_list(members)
                        first = members[0]  # Back-compat für {name}/{tag}/{user_id}
                        msg_template = (tpl.strip() or STD_MSG)
                        msg = (msg_template
                               .replace("{mention}", mentions_str)
                               .replace("{user_id}", str(first.id))
                               .replace("{tag}", str(first))
                               .replace("{name}", first.display_name))

                        if use_embed:
                            # Schlichtes, schönes Embed: Titel + Beschreibung (Template) + Timestamp + Footer
                            embed = discord.Embed(
                                title="🎂 Geburtstage heute",
                                description=msg,
                                colour=discord.Colour.blurple(),
                                timestamp=datetime.now(tz),
                            )
                            embed.set_footer(text="Alles Gute!")
                            try:
                                await channel.send(
                                    embed=embed,
                                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                                )
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                                logging.warning(f"[Birthday] Senden in Guild {g_id} (Channel {ch_id}) nicht möglich: {e}")
                        else:
                            try:
                                await channel.send(
                                    msg,
                                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
                                )
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                                logging.warning(f"[Birthday] Senden in Guild {g_id} (Channel {ch_id}) nicht möglich: {e}")

                        # Nächsten Termin je User in Guild-Zeitzone planen
                        for user_id, _birth_str, d, m, y in items:
                            new_epoch = _calc_next_epoch(d, m, tz, hr, mn)
                            async with self.bot.pool.acquire() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                                        (new_epoch, g_id, user_id)
                                    )
                    except (discord.NotFound, discord.Forbidden) as e:
                        logging.warning(f"[Birthday] Ressource nicht verfügbar / keine Rechte für Guild {g_id}: {e}")
                    except discord.HTTPException as e:
                        logging.warning(f"[Birthday] Discord HTTP-Fehler für Guild {g_id}: {e}")
                    except Exception as e:
                        logging.exception(f"[Birthday] Unerwarteter Fehler bei Verarbeitung von Guild {g_id}: {e}")

                wake = next_minute_utc(wake)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.exception(f"[Birthday] Unerwarteter Fehler im ticker-Loop: {e}")
                wake = next_minute_utc()

# ================= Slash-Commands (pro Guild) =================

@app_commands.guild_only()
class Geburtstag(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="geburtstag", description="Geburtstag einrichten/anzeigen & Server-Setup")
        self.bot = bot

    # ---- User: setzen/anzeigen/löschen ----

    @app_commands.command(name="setzen", description="Trage deinen Geburtstag ein.")
    @app_commands.describe(datum="Format: TT.MM.JJJJ (z. B. 11.08.2005)")
    async def setzen(self, interaction: discord.Interaction, datum: str):
        uid = interaction.user.id
        gid = interaction.guild.id
        try:
            born = datetime.strptime(datum.strip(), "%d.%m.%Y")
        except ValueError:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Falsches Format. Bitte **TT.MM.JJJJ** (z. B. `11.08.2005`).",
                ephemeral=True
            ); return
        d, m, y = born.day, born.month, born.year

        # Guild-Settings (time & tz)
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COALESCE(send_hour,9), COALESCE(send_minute,0), COALESCE(tz_name,%s) "
                    "FROM birthday_settings WHERE guild_id=%s",
                    (FALLBACK_TZ, gid)
                )
                row = await cur.fetchone()
        hr, mn, tz_name = (row if row else (9, 0, FALLBACK_TZ))
        tz = _safe_tz(tz_name)
        next_epoch = _calc_next_epoch(d, m, tz, int(hr), int(mn))

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 FROM birthdays_guild WHERE guild_id=%s AND user_id=%s", (gid, uid))
                if await cur.fetchone():
                    await interaction.response.send_message(
                        "<:Astra_wichtig:1141303951862534224> Du hast hier bereits einen Eintrag. Nutze **/geburtstag löschen** und dann **/geburtstag setzen**.",
                        ephemeral=True
                    ); return
                await cur.execute(
                    "INSERT INTO birthdays_guild (guild_id, user_id, birth_str, day, month, year, next_epoch) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (gid, uid, datum.strip(), d, m, y, next_epoch)
                )

        embed = discord.Embed(title="Geburtstag gespeichert", colour=discord.Colour.green())
        embed.add_field(name="<:Astra_calender:1141303828625489940> Geburtsdatum", value=datum.strip(), inline=False)
        embed.add_field(name="<:Astra_time:1141303932061233202> Nächster Geburtstag", value=f"<t:{next_epoch}:D> • <t:{next_epoch}:R>", inline=False)
        embed.set_footer(text=f"Gespeichert von {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anzeigen", description="Zeigt deinen gespeicherten Geburtstag an.")
    async def anzeigen(self, interaction: discord.Interaction):
        uid = interaction.user.id
        gid = interaction.guild.id
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT birth_str, next_epoch FROM birthdays_guild WHERE guild_id=%s AND user_id=%s",
                    (gid, uid)
                )
                row = await cur.fetchone()

        if not row:
            await interaction.response.send_message(
                "🎂 Du hast hier noch keinen Geburtstag gespeichert. Nutze **/geburtstag setzen**.",
                ephemeral=True
            ); return

        birth_str, next_epoch = row
        embed = discord.Embed(title="<:Astra_gw1:1141303852889550928>  Dein Geburtstag", colour=discord.Colour.blurple())
        embed.add_field(name="<:Astra_calender:1141303828625489940> Gespeichert als", value=birth_str, inline=False)
        embed.add_field(name="<:Astra_time:1141303932061233202> Nächster Geburtstag", value=f"<t:{next_epoch}:D> • <t:{next_epoch}:R>", inline=False)
        embed.set_footer(text=f"Angefragt von {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="löschen", description="Löscht deinen Geburtstagseintrag.")
    async def loeschen(self, interaction: discord.Interaction):
        uid = interaction.user.id
        gid = interaction.guild.id
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM birthdays_guild WHERE guild_id=%s AND user_id=%s", (gid, uid))
        await interaction.response.send_message(
            "<:Astra_accept:1141303821176422460> Dein Geburtstagseintrag wurde gelöscht.",
            ephemeral=True
        )

    # ---- Admin: Setup (Channel / Uhrzeit(HH:mm) / Zeitzone) ----

    @app_commands.command(name="setup", description="Channel, Uhrzeit & Zeitzone setzen/anzeigen.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Textkanal für Glückwünsche",
        uhrzeit="HH:mm (lokal zur Zeitzone)",
        zeitzone="IANA-Zeitzone, z. B. Europe/Berlin"
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        uhrzeit: Optional[str] = None,
        zeitzone: Optional[str] = None
    ):
        if not interaction.guild:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Nur in Servern verfügbar.", ephemeral=True); return

        gid = interaction.guild.id

        parsed_time = None
        if uhrzeit is not None:
            parsed_time = _parse_hhmm(uhrzeit)
            if parsed_time is None:
                await interaction.response.send_message("<:Astra_x:1141303954555289600> Ungültige Uhrzeit. Format **HH:mm** (z. B. `09:00`, `18:30`).", ephemeral=True); return

        tz_to_set = None
        if zeitzone is not None:
            try:
                ZoneInfo(zeitzone)
                tz_to_set = zeitzone
            except Exception:
                await interaction.response.send_message("<:Astra_x:1141303954555289600> Ungültige Zeitzone. Beispiele: `Europe/Berlin`, `Europe/Vienna`, `Europe/Zurich`.", ephemeral=True); return

        # Upsert (Alias-Technik, kein VALUES() im UPDATE) + selektive Updates
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO birthday_settings (guild_id, channel_id, message_template, send_hour, send_minute, tz_name, use_embed, enabled) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 1) AS new "
                    "ON DUPLICATE KEY UPDATE "
                    "channel_id=COALESCE(new.channel_id, channel_id), "
                    "message_template=IF(new.message_template='', message_template, new.message_template), "
                    "send_hour=new.send_hour, send_minute=new.send_minute, "
                    "tz_name=IFNULL(new.tz_name, tz_name), use_embed=IFNULL(new.use_embed, use_embed)",
                    (gid, channel.id if channel else None, "", 9, 0, FALLBACK_TZ, 1)
                )
                if channel is not None:
                    await cur.execute("UPDATE birthday_settings SET channel_id=%s WHERE guild_id=%s", (channel.id, gid))
                if parsed_time is not None:
                    hh, mm = parsed_time
                    await cur.execute("UPDATE birthday_settings SET send_hour=%s, send_minute=%s WHERE guild_id=%s", (hh, mm, gid))
                if tz_to_set is not None:
                    await cur.execute("UPDATE birthday_settings SET tz_name=%s WHERE guild_id=%s", (tz_to_set, gid))

                await cur.execute(
                    "SELECT COALESCE(channel_id,0), COALESCE(message_template,''), COALESCE(send_hour,9), "
                    "COALESCE(send_minute,0), COALESCE(tz_name,%s), COALESCE(use_embed,1), COALESCE(enabled,1) "
                    "FROM birthday_settings WHERE guild_id=%s",
                    (FALLBACK_TZ, gid)
                )
                ch_id, tpl, hour, minute, tz_name, use_embed, enabled = await cur.fetchone()

        # Recalculate alle next_epoch dieser Guild
        tz = _safe_tz(tz_name)
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT user_id, day, month FROM birthdays_guild WHERE guild_id=%s", (gid,))
                rows = await cur.fetchall()

        updates = []
        ref = datetime.now(tz)
        for user_id, day, month in rows:
            try:
                new_epoch = _calc_next_epoch(int(day), int(month), tz, int(hour), int(minute), ref=ref)
                updates.append((new_epoch, gid, int(user_id)))
            except Exception:
                continue
        if updates:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "UPDATE birthdays_guild SET next_epoch=%s WHERE guild_id=%s AND user_id=%s",
                        updates
                    )

        ch_mention = f"<#{ch_id}>" if ch_id else "—"
        tpl_eff = tpl or STD_MSG
        hhmm = f"{int(hour):02d}:{int(minute):02d}"
        mode = "Embed" if int(use_embed) == 1 else "Text"
        status = "AN ✅" if int(enabled) == 1 else "AUS ⛔"
        embed = discord.Embed(title="🎛️ Geburtstag-Setup", colour=discord.Colour.blurple())
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Channel", value=ch_mention, inline=True)
        embed.add_field(name="Uhrzeit", value=hhmm, inline=True)
        embed.add_field(name="Zeitzone", value=tz_name, inline=True)
        embed.add_field(name="Nachrichtenvorlage", value=f"`{tpl_eff}`", inline=False)
        embed.add_field(name="Modus", value=mode, inline=True)
        embed.set_footer(text="Platzhalter: {mention}, {user_id}, {tag}, {name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---- Admin: Nachrichtenvorlage per Modal (inkl. Ja/Nein für Embed) ----

    @app_commands.command(name="nachricht", description="Eigene Geburtstagsnachricht setzen.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def nachricht(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Nur in Servern verfügbar.", ephemeral=True); return

        gid = interaction.guild.id

        # Bestehendes Template/Modus
        current_tpl = ""
        current_use_embed = 1
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COALESCE(message_template,''), COALESCE(use_embed,1) FROM birthday_settings WHERE guild_id=%s", (gid,))
                row = await cur.fetchone()
                if row:
                    current_tpl = row[0] or ""
                    current_use_embed = int(row[1])

        class MsgModal(discord.ui.Modal, title="Nachrichtenvorlage bearbeiten"):
            text = discord.ui.TextInput(
                label="Vorlage",
                style=discord.TextStyle.paragraph,
                placeholder=current_tpl or STD_MSG,
                max_length=500,
                required=False
            )
            embed_flag = discord.ui.TextInput(
                label="Als Embed senden? (ja/nein)",
                style=discord.TextStyle.short,
                placeholder="ja" if current_use_embed else "nein",
                required=False,
                max_length=5
            )

            def __init__(self, bot: commands.Bot):
                super().__init__()
                self.bot = bot

            async def on_submit(self, modal_interaction: discord.Interaction):
                tpl_val = (self.text.value or "").strip()
                flag = (self.embed_flag.value or ("ja" if current_use_embed else "nein")).strip().lower()
                use_embed = 1 if flag in ("ja", "j", "yes", "y") else 0

                async with self.bot.pool.acquire() as conn2:
                    async with conn2.cursor() as cur2:
                        await cur2.execute(
                            "INSERT INTO birthday_settings (guild_id, message_template, use_embed) "
                            "VALUES (%s,%s,%s) AS new "
                            "ON DUPLICATE KEY UPDATE message_template=new.message_template, use_embed=new.use_embed",
                            (modal_interaction.guild.id, tpl_val, use_embed)
                        )
                preview = tpl_val or STD_MSG
                mode = "Embed" if use_embed else "Text"
                await modal_interaction.response.send_message(
                    f"<:Astra_accept:1141303821176422460> Nachrichtenvorlage aktualisiert ({mode}-Modus):\n```{preview}```",
                    ephemeral=True
                )

        await interaction.response.send_modal(MsgModal(self.bot))


    @app_commands.command(name="status", description="Aktiviere oder deaktiviere das Geburtstagssystem.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(modus="Wähle 'an' um zu aktivieren oder 'aus' um zu pausieren.")
    async def status(self, interaction: discord.Interaction, modus: Literal["Einschalten", "Ausschalten"]):
        if not interaction.guild:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Nur in Servern verfügbar.",
                                                    ephemeral=True)
            return

        gid = interaction.guild.id
        new_enabled = 1 if modus == "Einschalten" else 0

        # Upsert enabled-Flag in birthday_settings
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO birthday_settings (guild_id, enabled) "
                    "VALUES (%s, %s) AS new "
                    "ON DUPLICATE KEY UPDATE enabled = new.enabled",
                    (gid, new_enabled)
                )
                await cur.execute(
                    "SELECT COALESCE(channel_id,0), COALESCE(send_hour,9), COALESCE(send_minute,0), "
                    "COALESCE(tz_name,%s), COALESCE(use_embed,1), COALESCE(enabled,1), COALESCE(message_template,'') "
                    "FROM birthday_settings WHERE guild_id=%s",
                    (FALLBACK_TZ, gid)
                )
                ch_id, hour, minute, tz_name, use_embed, enabled, tpl = await cur.fetchone()

        status_txt = "✅ Aktiviert" if int(enabled) == 1 else "⛔ Deaktiviert"
        ch_mention = f"<#{ch_id}>" if ch_id else "—"
        hhmm = f"{int(hour):02d}:{int(minute):02d}"
        mode_txt = "Embed" if int(use_embed) == 1 else "Text"
        tpl_eff = tpl or STD_MSG

        embed = discord.Embed(
            title="⚙️ Geburtstagssystem – Status geändert",
            colour=discord.Colour.green() if enabled else discord.Colour.red(),
            description=f"Das Geburtstagssystem wurde **{status_txt.lower()}**."
        )
        embed.add_field(name="Status", value=status_txt, inline=True)
        embed.add_field(name="Channel", value=ch_mention, inline=True)
        embed.add_field(name="Uhrzeit", value=hhmm, inline=True)
        embed.add_field(name="Zeitzone", value=tz_name, inline=True)
        embed.add_field(name="Modus", value=mode_txt, inline=True)
        embed.add_field(name="Vorlage", value=f"`{tpl_eff}`", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---- Autocomplete: Zeitzone ----
    @setup.autocomplete("zeitzone")
    async def tz_autocomplete(self, interaction: discord.Interaction, current: str):
        current_lower = (current or "").lower()
        choices = [tz for tz in ALLOWED_TZS if current_lower in tz.lower()]
        return [app_commands.Choice(name=tz, value=tz) for tz in choices[:25]]

# ================= Bot-Hooks =================

async def setup(bot: commands.Bot):
    await bot.add_cog(Birthday(bot))
    bot.tree.add_command(Geburtstag(bot))
