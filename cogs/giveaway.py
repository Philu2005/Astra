import asyncio
import logging
import math
import random
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands


# ----------------------------- Utils -----------------------------
def convert(time_str: str) -> int:
    """
    Konvertiert '10m', '2h', '3d', '1w' in Sekunden.
    -1: ungültige Einheit, -2: Value-Fehler.
    """
    pos = ["s", "m", "h", "d", "w"]
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24, "w": 3600 * 24 * 7}
    unit = time_str[-1]
    if unit not in pos:
        return -1
    try:
        val = int(time_str[:-1])
    except Exception:
        return -2
    return val * time_dict[unit]


def _to_int_or_none(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    s = str(v).strip()
    if s.lower() in {"", "not set", "none", "null", "nil"}:
        return None
    try:
        iv = int(s)           # <— direkt parsen, kein float!
        return iv if iv > 0 else None
    except Exception:
        return None



# ------------------------- Giveaway End-Timer -------------------------
async def gwtimes(bot: commands.Bot, when: datetime, messageid: int):
    """Wartet bis 'when' und beendet dann das Giveaway (messageid)."""
    await bot.wait_until_ready()
    await discord.utils.sleep_until(when=when)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT guildID, channelID, userID, messageID FROM giveaway_entrys WHERE messageID = %s",
                (messageid,),
            )
            result = await cur.fetchall()

            await cur.execute(
                "SELECT ended, prize, winners, entrys, time, guildID, channelID "
                "FROM giveaway_active WHERE messageID = %s",
                (messageid,),
            )
            row = await cur.fetchone()
            if not row:
                return

            ended, prize, winners, entrys, time_unix, guildID, channelID = row

            guild = bot.get_guild(int(guildID))
            if guild is None:
                logging.error(f"Guild {guildID} not found for giveaway {messageid}!")
                return

            channel = guild.get_channel(int(channelID))
            if channel is None:
                logging.error(f"Channel {channelID} not found in guild {guildID} for giveaway {messageid}!")
                return

            try:
                msg = await channel.fetch_message(int(messageid))
            except Exception as e:
                logging.error(f"Giveaway message {messageid} not found: {e}")
                return

            end_dt = datetime.fromtimestamp(int(time_unix), tz=timezone.utc)

            if int(ended) == 1:
                return

            if not result:
                # niemand teilgenommen
                embed = discord.Embed(
                    title=" ",
                    description=(
                        f"🏆 Preis: {prize}\n"
                        "`🤖` [Astra Einladen]"
                        "(https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                        "<:Astra_gw_open2:1141303850125504533> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                        "<:Astra_arrow:1141303823600717885> Niemand hat das Gewinnspiel gewonnen.\n"
                        f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                        "<:Astra_arrow:1141303823600717885> Es gab **0** Teilnehmer."
                    ),
                    colour=discord.Colour.red(),
                )
                await msg.edit(content="`❌` Giveaway Ended `❌`", embed=embed, view=None)
                await msg.reply("<:Astra_x:1141303954555289600> **Es gab nicht genügend Teilnehmer. Niemand hat das Gewinnspiel gewonnen.**")
            else:
                # es gibt Teilnehmer
                participants = [row[2] for row in result]
                to_pick = min(len(participants), int(winners)) if participants else 0
                chosen = random.sample(participants, k=to_pick) if to_pick > 0 else []

                users = []
                for uid in chosen:
                    u = bot.get_user(int(uid))
                    if not u:
                        continue
                    win = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen]"
                            "(https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            f"`🎉` Du hast ein Gewinnspiel auf [{guild.name}]"
                            f"(https://discord.com/channels/{guild.id}/{channel.id}/{msg.id}) gewonnen.\n"
                            f"`⏰` Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}"
                        ),
                        colour=discord.Colour.yellow(),
                    )
                    if guild.icon:
                        win.set_thumbnail(url=guild.icon.url)
                    try:
                        await u.send("<:Astra_herz:1141303857855594527> **Du hast ein Gewinnspiel gewonnen! Herzlichen Glückwunsch.**", embed=win)
                    except Exception:
                        pass
                    users.append(u)

                mentions = ", ".join(u.mention for u in users if u)
                if entrys < 1 or not users:
                    embed = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen]"
                            "(https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            "<:Astra_gw_open2:1141303850125504533> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                            "<:Astra_arrow:1141303823600717885> Niemand hat das Gewinnspiel gewonnen.\n"
                            f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                            "<:Astra_arrow:1141303823600717885> Es gab **0** Teilnehmer."
                        ),
                        colour=discord.Colour.red(),
                    )
                    await msg.edit(content="`❌` Giveaway Ended `❌`", embed=embed, view=None)
                    await msg.reply("<:Astra_x:1141303954555289600> Es gab nicht genügend Teilnehmer. Niemand hat das Gewinnspiel gewonnen.")
                else:
                    embed = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen]"
                            "(https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            "<:Astra_gw_open2:1141303850125504533> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                            f"<:Astra_arrow:1141303823600717885> {mentions} hat das Gewinnspiel gewonnen.\n"
                            f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                            f"<:Astra_arrow:1141303823600717885> Es gab **{entrys}** Teilnehmer."
                        ),
                        colour=discord.Colour.red(),
                    )
                    await msg.edit(content="`❌` Giveaway Ended `❌`", embed=embed, view=None)
                    await msg.reply(f"<:Astra_gw1:1141303852889550928> {mentions} hat das Gewinnspiel gewonnen! Herzlichen Glückwunsch.")

            # Endstatus & Aufräumen
            await cur.execute(
                "UPDATE giveaway_active SET ended = %s WHERE guildID = %s AND channelID = %s and messageID = %s",
                (1, guild.id, channel.id, messageid),
            )
            await cur.execute("DELETE FROM giveway_ids WHERE messageID = %s", (messageid,))
            await cur.execute("DELETE FROM giveaway_entrys WHERE messageID = %s", (messageid,))

            # Wenn KEIN anderes aktives Gewinnspiel mehr in der Guild läuft -> Message-Counts löschen
            await cur.execute("SELECT 1 FROM giveaway_active WHERE guildID = %s AND ended = 0 LIMIT 1", (guild.id,))
            still_active = await cur.fetchone()
            if not still_active:
                await cur.execute("DELETE FROM user_message_counts WHERE guildID = %s", (guild.id,))


# --------------------------- Button View ---------------------------
class GiveawayButton(discord.ui.View):
    """Persistente View mit Teilnahme-/Abmelde-Button."""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Teilnehmen",
        style=discord.ButtonStyle.green,
        custom_id="persistent_view_allg:join_gw",
        emoji="<:Astra_gw1:1141303852889550928>",
    )
    async def join_gw(self, interaction: discord.Interaction, button: discord.Button):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await interaction.response.defer(ephemeral=True)

                # Bereits eingetragen?
                await cur.execute(
                    "SELECT userID FROM giveaway_entrys WHERE userID = %s AND guildID = %s AND channelID = %s AND messageID = %s",
                    (interaction.user.id, interaction.guild.id, interaction.channel.id, interaction.message.id),
                )
                existing = await cur.fetchone()

                # Giveaway-Infos inkl. Anforderungen
                await cur.execute(
                    "SELECT role, role_name, level, entrys, messageID, prize, winners, time, creatorID, messages_required "
                    "FROM giveaway_active WHERE guildID = %s AND channelID = %s AND messageID = %s",
                    (interaction.guild.id, interaction.channel.id, interaction.message.id),
                )
                row = await cur.fetchone()
                if not row:
                    return

                role_raw, role_name_raw, level_raw, entrys, messageID, prize, winners, time_unix, creatorID, msgs_req_raw = row
                role_id = _to_int_or_none(role_raw)
                role_name = (str(role_name_raw).strip() if role_name_raw else None)
                level_req = _to_int_or_none(level_raw)
                msgs_req = _to_int_or_none(msgs_req_raw)

                guild = interaction.guild
                creator = self.bot.get_user(int(creatorID)) or guild.get_member(int(creatorID))
                t_end = datetime.fromtimestamp(int(time_unix), tz=timezone.utc)

                # Anforderungen Block (öffentlich) – schöne Sätze, korrektes level_req
                req_parts = []
                if role_name or role_id:
                    req_parts.append(f"<:Astra_punkt:1141303896745201696> Du benötigt die Rolle: **{role_name}**, um teilzunehmen.")
                if level_req is not None:
                    req_parts.append(f"<:Astra_punkt:1141303896745201696> Du musst mindestens Level: **{int(level_req)}** sein, um teilzunehmen.")
                if msgs_req is not None:
                    req_parts.append(f"<:Astra_punkt:1141303896745201696> Du musst mindestens **{int(msgs_req)}** Nachrichten schreiben, um teilzunehmen.")
                req_block = ("\n" + "\n".join(req_parts)) if req_parts else ""

                # Embed-Funktionen
                def public_embed(current_count: int) -> discord.Embed:
                    e = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            "<:Astra_info:1141303860556738620> » __**Informationen:**__\n"
                            f"<:Astra_arrow:1141303823600717885> Erstellt von {getattr(creator, 'mention', interaction.user.mention)}\n"
                            f"<:Astra_arrow:1141303823600717885> **{winners}** Gewinner\n"
                            f"<:Astra_arrow:1141303823600717885> Gewinnspiel endet {discord.utils.format_dt(t_end, 'R')}\n"
                            f"<:Astra_arrow:1141303823600717885> **{current_count}** Teilnehmer\n\n"
                            "<:Astra_settings:1141303908778639490> » __**Anforderungen:**__\n"
                            "<:Astra_arrow:1141303823600717885> **Klicke** unten auf den **Button**, um teilzunehmen."
                            f"{req_block}"
                        ),
                        colour=discord.Colour.blue(),
                    )
                    if guild and guild.icon:
                        e.set_thumbnail(url=guild.icon.url)
                        e.set_footer(text="Viel Erfolg 🍀", icon_url=guild.icon.url)
                    else:
                        e.set_footer(text="Viel Erfolg 🍀")
                    return e

                def success_dm() -> discord.Embed:
                    e = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            f"`🎉` Deine Teilnahme auf [{guild.name}](https://discord.com/channels/{guild.id}/{interaction.channel.id}/{messageID}) war erfolgreich.\n"
                            f"`⏰` Das Gewinnspiel endet {discord.utils.format_dt(t_end, 'R')}."
                        ),
                        colour=discord.Colour.green(),
                    )
                    if guild and guild.icon:
                        e.set_thumbnail(url=guild.icon.url)
                    return e

                # --- Anforderungen prüfen & Gründe als Sätze ---
                reasons_lines = []
                role_ok, lvl_ok, msgs_ok = True, True, True
                have_level, have_msgs = 0, 0

                member: Optional[discord.Member] = guild.get_member(interaction.user.id)

                # Rolle
                if role_id is not None or role_name:
                    shown = role_name or str(role_id)
                    role_ok = False
                    target_role = None
                    if role_id is not None:
                        target_role = guild.get_role(role_id)
                    if target_role is None and role_name:
                        target_role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), guild.roles)
                    if target_role and member:
                        role_ok = target_role in member.roles
                    if not role_ok:
                        reasons_lines.append(f"<:Astra_punkt:1141303896745201696> Du benötigst die Rolle **{shown}**, um teilnehmen zu können.")

                # Level
                if level_req is not None:
                    await cur.execute(
                        "SELECT user_level FROM levelsystem WHERE client_id = %s AND guild_id = %s",
                        (interaction.user.id, guild.id),
                    )
                    row_lvl = await cur.fetchone()
                    have_level = int(row_lvl[0]) if row_lvl and row_lvl[0] is not None else 0
                    lvl_ok = have_level >= level_req
                    if not lvl_ok:
                        diff = level_req - have_level
                        reasons_lines.append(f"<:Astra_punkt:1141303896745201696> Du benötigst noch **{diff} Level**, um teilnehmen zu können.")

                # Nachrichten
                if msgs_req is not None:
                    await cur.execute(
                        "SELECT count FROM user_message_counts WHERE guildID = %s AND userID = %s",
                        (guild.id, interaction.user.id),
                    )
                    row_msg = await cur.fetchone()
                    have_msgs = int(row_msg[0]) if row_msg and row_msg[0] is not None else 0
                    msgs_ok = have_msgs >= msgs_req
                    if not msgs_ok:
                        diff = msgs_req - have_msgs
                        reasons_lines.append(f"<:Astra_punkt:1141303896745201696> Dir fehlen noch **{diff} Nachrichten**, um teilnehmen zu können.")

                any_failed = not (role_ok and lvl_ok and msgs_ok)

                def failure_dm() -> discord.Embed:
                    e = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {prize}\n"
                            "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            f"`🎉` Deine Teilnahme auf [{guild.name}](https://discord.com/channels/{guild.id}/{interaction.channel.id}/{messageID}) war **nicht** erfolgreich.\n"
                            f"`⏰` Das Gewinnspiel endet {discord.utils.format_dt(t_end, 'R')}.\n\n"
                            "`🧨` __**Gründe**__\n" + "\n".join(reasons_lines)
                        ),
                        colour=discord.Colour.red(),
                    )
                    if guild and guild.icon:
                        e.set_thumbnail(url=guild.icon.url)
                    return e

                # Teilnahme eintragen / austragen
                if not existing:
                    if not any_failed:
                        new_count = int(entrys) + 1
                        msg_obj = await interaction.channel.fetch_message(int(messageID))
                        await msg_obj.edit(embed=public_embed(new_count))
                        await cur.execute(
                            "UPDATE giveaway_active SET entrys = %s WHERE guildID = %s AND channelID = %s AND messageID = %s",
                            (new_count, guild.id, interaction.channel.id, interaction.message.id),
                        )
                        await cur.execute(
                            "INSERT INTO giveaway_entrys(guildID, channelID, userID, messageID) VALUES (%s, %s, %s, %s)",
                            (guild.id, interaction.channel.id, interaction.user.id, interaction.message.id),
                        )
                        try:
                            await interaction.user.send(
                                "**<:Astra_accept:1141303821176422460> Deine Teilnahme am Gewinnspiel war erfolgreich.**",
                                embed=success_dm(),
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await interaction.user.send(
                                "**<:Astra_x:1141303954555289600> Deine Teilnahme am Gewinnspiel war nicht erfolgreich.**",
                                embed=failure_dm(),
                            )
                        except Exception:
                            pass
                    return

                # Abmelden
                new_count = max(int(entrys) - 1, 0)
                await cur.execute(
                    "DELETE FROM giveaway_entrys WHERE userID = %s AND guildID = %s AND messageID = %s",
                    (interaction.user.id, guild.id, interaction.message.id),
                )
                await cur.execute(
                    "UPDATE giveaway_active SET entrys = %s WHERE channelID = %s AND guildID = %s AND messageID = %s",
                    (new_count, interaction.channel.id, guild.id, interaction.message.id),
                )
                msg_obj = await interaction.channel.fetch_message(int(messageID))
                await msg_obj.edit(embed=public_embed(new_count))
                try:
                    await interaction.user.send(
                        "**<:Astra_accept:1141303821176422460> Du hast deine Teilnahme am Gewinnspiel erfolgreich zurückgezogen.**"
                    )
                except Exception:
                    pass

# ---------------------------- Slash-Gruppe ----------------------------
@app_commands.guild_only()
class Giveaway(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__(name="gewinnspiel", description="Alles rund um Gewinnspiele.")

    @app_commands.command(name="starten", description="Startet ein Gewinnspiel.")
    @app_commands.describe(preis="Der Preis des Gewinnspiels.")
    @app_commands.describe(kanal="Der Kanal, in dem das Gewinnspiel stattfinden soll.")
    @app_commands.describe(gewinner="Anzahl der Gewinner.")
    @app_commands.describe(zeit="Dauer (z. B. 10m, 2h, 3d).")
    @app_commands.describe(rolle="Optional: Rolle, die teilnehmen darf.")
    @app_commands.describe(level="Optional: Mindestlevel.")
    @app_commands.describe(nachrichten="Optional: Mindestanzahl an Nachrichten (serverweit).")
    @app_commands.checks.has_permissions(manage_events=True)
    async def gw_start(
        self,
        interaction: discord.Interaction,
        *,
        preis: str,
        kanal: discord.TextChannel,
        gewinner: int,
        zeit: str,
        rolle: discord.Role | None = None,
        level: int | None = None,
        nachrichten: int | None = None,
    ):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if level:
                    await cur.execute("SELECT enabled FROM levelsystem WHERE guild_id = %s", (interaction.guild.id,))
                    enabled = await cur.fetchone()
                    if not enabled or enabled[0] == 0:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Das Levelsystem ist auf diesem Server deaktiviert.",
                            ephemeral=True,
                        )
                        return

                secs = convert(zeit)
                t1 = math.floor(discord.utils.utcnow().timestamp() + secs)
                t2 = datetime.fromtimestamp(t1, tz=timezone.utc)

                msgs_req = nachrichten if isinstance(nachrichten, int) and nachrichten > 0 else None

                # Anforderungen-Block (wir speichern ID und NAME)
                role_id = rolle.id if rolle else None
                role_name = rolle.name if rolle else None

                req_parts = []

                if role_name or role_id:
                    display_role = role_name
                    req_parts.append(
                        f"<:Astra_punkt:1141303896745201696> Du benötigst die Rolle **{display_role}**, um teilzunehmen."
                    )

                if level is not None:
                    lvl_val = int(level)
                    req_parts.append(
                        f"<:Astra_punkt:1141303896745201696> Du musst mindestens Level: **{lvl_val}** sein, um teilzunehmen."
                    )

                if msgs_req is not None:
                    msgs_val = int(msgs_req)
                    req_parts.append(
                        f"<:Astra_punkt:1141303896745201696> Du musst mindestens **{msgs_val}** Nachrichten schreiben, um teilzunehmen."
                    )

                req_block = ("\n" + "\n".join(req_parts)) if req_parts else ""

                embed = discord.Embed(
                    title=" ",
                    description=(
                        f"🏆 Preis: {preis}\n"
                        "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                        "<:Astra_info:1141303860556738620> » __**Informationen:**__\n"
                        f"<:Astra_arrow:1141303823600717885> Erstellt von {interaction.user.mention}\n"
                        f"<:Astra_arrow:1141303823600717885> **{gewinner}** Gewinner\n"
                        f"<:Astra_arrow:1141303823600717885> Gewinnspiel endet {discord.utils.format_dt(t2, 'R')}\n"
                        f"<:Astra_arrow:1141303823600717885> **0** Teilnehmer\n\n"
                        "<:Astra_settings:1141303908778639490> » __**Anforderungen:**__\n"
                        "<:Astra_arrow:1141303823600717885> **Klicke** unten auf den **Button** um teilzunehmen."
                        f"{req_block}"
                    ),
                    colour=discord.Colour.blue(),
                )
                if interaction.guild and interaction.guild.icon:
                    embed.set_thumbnail(url=interaction.guild.icon.url)
                    embed.set_footer(text="Viel Erfolg 🍀", icon_url=interaction.guild.icon.url)
                else:
                    embed.set_footer(text="Viel Erfolg 🍀")

                msg = await kanal.send("🎉 **Neues Gewinnspiel** 🎉", embed=embed, view=GiveawayButton(self.bot))

                asyncio.create_task(gwtimes(self.bot, t2, msg.id))

                # In DB speichern (inkl. role_name)
                await cur.execute(
                    "INSERT INTO giveaway_active (guildID, creatorID, channelID, entrys, messageID, prize, winners, time, role, role_name, level, messages_required, ended) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        interaction.guild.id,
                        interaction.user.id,
                        kanal.id,
                        0,
                        msg.id,
                        preis,
                        gewinner,
                        t1,
                        role_id if role_id is not None else "Not Set",
                        role_name if role_name is not None else None,
                        level if level is not None else "Not Set",
                        msgs_req,
                        0,
                    ),
                )

                await cur.execute("SELECT gwID FROM giveway_ids WHERE guildID = %s", (interaction.guild.id,))
                rows = await cur.fetchall()
                new_gw_id = (len(rows) + 1) if rows else 1
                await cur.execute(
                    "INSERT INTO giveway_ids (guildID, gwID, messageID) VALUES (%s, %s, %s)",
                    (interaction.guild.id, new_gw_id, msg.id),
                )

                await interaction.response.send_message(
                    f"**<:Astra_accept:1141303821176422460> Das Gewinnspiel wird in {kanal.mention} stattfinden.**"
                )

    @app_commands.command(name="verwalten", description="Verwalte ein Gewinnspiel.")
    @app_commands.describe(aktion="Aktion, die durchgeführt werden soll.")
    @app_commands.describe(messageid="Nachrichten-ID des Gewinnspiels (falls benötigt).")
    @app_commands.checks.has_permissions(manage_events=True)
    async def gw_verwalten(
            self,
            interaction: discord.Interaction,
            * ,
            aktion: Literal[
                "Gewinnspiel beenden(Nachrichten ID angeben)",
                "Gewinnspiel neu würfeln(Nachrichten ID angeben)",
                "Gewinnspiele Anzeigen",
            ],
            messageid: str | None = None,
    ):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                # Anzeigen
                if aktion == "Gewinnspiele Anzeigen":
                    await cur.execute("SELECT gwID, messageID FROM giveway_ids WHERE guildID = %s", (interaction.guild.id,))
                    result = await cur.fetchall()
                    if not result:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> **Es gibt keine aktiven Gewinnspiele auf diesem Server.**",
                            ephemeral=True,
                        )
                        return

                    embed = discord.Embed(
                        title=f"Alle Gewinnspiele auf {interaction.guild.name}",
                        description="Um ein Gewinnspiel zu erstellen, nutze `/gewinnspiel starten`.",
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.set_author(name=str(interaction.user), icon_url=(interaction.user.avatar.url if interaction.user.avatar else discord.Embed.Empty))

                    for gwid, mid in result:
                        await cur.execute("SELECT time FROM giveaway_active WHERE guildID = %s AND messageID = %s", (interaction.guild.id, mid))
                        time_result = await cur.fetchone()
                        if time_result:
                            unix_time = int(time_result[0])
                            embed.add_field(
                                name=f"ID: {gwid}",
                                value=f"<:Astra_time:1141303932061233202> Das Gewinnspiel endet: <t:{unix_time}:F>",
                                inline=False,
                            )

                    await interaction.response.send_message(embed=embed)
                    return

                # ID nötig
                if not messageid:
                    await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Bitte gib eine Nachrichten-ID an!**",
                        ephemeral=True,
                    )
                    return

                # Beenden
                if aktion == "Gewinnspiel beenden(Nachrichten ID angeben)":
                    await cur.execute("SELECT guildID, channelID, userID FROM giveaway_entrys WHERE messageID = %s", (messageid,))
                    entrys_result = await cur.fetchall()
                    await cur.execute(
                        "SELECT prize, winners, entrys, time, guildID, channelID, ended, role, role_name, level, messages_required "
                        "FROM giveaway_active WHERE messageID = %s",
                        (messageid,),
                    )
                    gw = await cur.fetchone()
                    if not gw:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Kein aktives Gewinnspiel mit dieser Nachricht gefunden.**", ephemeral=True)
                        return

                    preis, winners, entrys, end_time, guildID, channelID, ended, role_raw, role_name_raw, level_raw, msgs_req_raw = gw
                    role_id = _to_int_or_none(role_raw)
                    role_name = (str(role_name_raw).strip() if role_name_raw else None)
                    level_req = _to_int_or_none(level_raw)
                    msgs_req = _to_int_or_none(msgs_req_raw)

                    guild = self.bot.get_guild(int(guildID))
                    if guild is None:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Guild nicht gefunden.**", ephemeral=True)
                        return

                    channel = guild.get_channel(int(channelID))
                    if channel is None:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Channel nicht gefunden.**", ephemeral=True)
                        return

                    try:
                        msg = await channel.fetch_message(int(messageid))
                    except Exception:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Nachricht nicht gefunden.**", ephemeral=True)
                        return

                    end_dt = datetime.fromtimestamp(int(end_time), tz=timezone.utc)

                    if ended:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Das Gewinnspiel ist bereits beendet!**", ephemeral=True)
                        return

                    if not entrys_result:
                        embed = discord.Embed(
                            title=" ",
                            description=(
                                f"🏆 Preis: {preis}\n"
                                "`🤖` [Invite Astra here](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                                "<:Astra_gw_open2:1061384624951021578> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                                "<:Astra_arrow:1141303823600717885> Niemand hat das Gewinnspiel gewonnen.\n"
                                f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                                "<:Astra_arrow:1141303823600717885> Es gab **0** Teilnehmer."
                            ),
                            colour=discord.Colour.red(),
                        )
                        await msg.edit(content="`❌` Gewinnspiel Vorbei `❌`", embed=embed, view=None)
                        await msg.reply("<:Astra_x:1141303954555289600> **Es gab nicht genügend Teilnehmer. Niemand hat das Gewinnspiel gewonnen.**")
                    else:
                        # valide Teilnehmer (Anforderungen nur zum Filtern)
                        raw_user_ids = [row[2] for row in entrys_result]
                        valid_ids: list[int] = []
                        for uid in raw_user_ids:
                            member = guild.get_member(int(uid))
                            if not member:
                                continue
                            ok = True
                            if role_id is not None:
                                r = guild.get_role(role_id)
                                if not r or r not in member.roles:
                                    ok = False
                            if ok and level_req is not None:
                                await cur.execute(
                                    "SELECT user_level FROM levelsystem WHERE client_id = %s AND guild_id = %s",
                                    (member.id, guild.id),
                                )
                                row_lvl = await cur.fetchone()
                                have_level = int(row_lvl[0]) if row_lvl and row_lvl[0] is not None else 0
                                if have_level < level_req:
                                    ok = False
                            if ok and msgs_req is not None:
                                await cur.execute(
                                    "SELECT count FROM user_message_counts WHERE guildID = %s AND userID = %s",
                                    (guild.id, member.id),
                                )
                                row_msg = await cur.fetchone()
                                have_msgs = int(row_msg[0]) if row_msg and row_msg[0] is not None else 0
                                if have_msgs < msgs_req:
                                    ok = False
                            if ok:
                                valid_ids.append(int(uid))

                        if not valid_ids:
                            embed = discord.Embed(
                                title=" ",
                                description=(
                                    f"🏆 Preis: {preis}\n"
                                    "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                                    "<:Astra_gw_open2:1061384624951021578> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                                    "<:Astra_arrow:1141303823600717885> Niemand hat gewonnen – **keiner** erfüllte die Anforderungen.\n"
                                    f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                                ),
                                colour=discord.Colour.red(),
                            )
                            await msg.edit(content="`❌` Gewinnspiel Vorbei `❌`", embed=embed, view=None)
                            await msg.reply("**Es gab keine gültigen Teilnehmer.**")
                        else:
                            winners_count = min(len(valid_ids), int(winners))
                            winners_ids = random.sample(valid_ids, k=winners_count)
                            users = [self.bot.get_user(uid) for uid in winners_ids]
                            mentions = ", ".join(u.mention for u in users if u)

                            for u in users:
                                if u:
                                    win = discord.Embed(
                                        title=" ",
                                        description=(
                                            f"🏆 Preis: {preis}\n"
                                            "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                                            f"`🎉` Du hast ein Gewinnspiel auf [{guild.name}](https://discord.com/channels/{guild.id}/{channel.id}/{msg.id}) gewonnen.\n"
                                            f"`⏰` Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}"
                                        ),
                                        colour=discord.Colour.yellow(),
                                    )
                                    if guild.icon:
                                        win.set_thumbnail(url=guild.icon.url)
                                    try:
                                        await u.send("<:Astra_herz:1141303857855594527> **Du hast ein Gewinnspiel gewonnen! Herzlichen Glückwunsch.**", embed=win)
                                    except Exception:
                                        pass

                            embed = discord.Embed(
                                title=" ",
                                description=(
                                    f"🏆 Preis: {preis}\n"
                                    "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                                    "<:Astra_gw_open2:1061384624951021578> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                                    f"<:Astra_arrow:1141303823600717885> {mentions} hat das Gewinnspiel gewonnen.\n"
                                    f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                                    f"<:Astra_arrow:1141303823600717885> Es gab **{entrys}** Teilnehmer."
                                ),
                                colour=discord.Colour.red(),
                            )
                            await msg.edit(content="`❌` Gewinnspiel Vorbei `❌`", embed=embed, view=None)
                            await msg.reply(f"<:Astra_gw1:1141303852889550928> {mentions} hat das Gewinnspiel gewonnen. Herzlichen Glückwunsch.")

                    # Endstatus & Aufräumen
                    await cur.execute(
                        "UPDATE giveaway_active SET ended = %s WHERE guildID = %s AND channelID = %s AND messageID = %s",
                        (1, guildID, channelID, messageid),
                    )
                    await cur.execute("DELETE FROM giveway_ids WHERE messageID = %s", (messageid,))
                    await cur.execute("DELETE FROM giveaway_entrys WHERE messageID = %s", (messageid,))

                    # Falls kein weiteres aktives Gewinnspiel -> Counts löschen
                    await cur.execute("SELECT 1 FROM giveaway_active WHERE guildID = %s AND ended = 0 LIMIT 1", (interaction.guild.id,))
                    still_active = await cur.fetchone()
                    if not still_active:
                        await cur.execute("DELETE FROM user_message_counts WHERE guildID = %s", (interaction.guild.id,))

                    await interaction.response.send_message(
                        "<:Astra_accept:1141303821176422460> **Das Gewinnspiel wurde erfolgreich beendet.**",
                        ephemeral=True,
                    )
                    return

                # Neu würfeln
                if aktion == "Gewinnspiel neu würfeln(Nachrichten ID angeben)":
                    await cur.execute(
                        "SELECT channelID, prize, winners, entrys, time, ended, role, role_name, level, messages_required "
                        "FROM giveaway_active WHERE guildID = %s AND messageID = %s",
                        (interaction.guild.id, int(messageid)),
                    )
                    gw = await cur.fetchone()
                    if not gw:
                        await interaction.response.send_message(
                            f"<:Astra_x:1141303954555289600> Es gibt kein Gewinnspiel mit der ID {messageid}!",
                            ephemeral=True,
                        )
                        return

                    channelID, preis, winners, entrys, end_time, ended, role_raw, role_name_raw, level_raw, msgs_req_raw = gw
                    role_id = _to_int_or_none(role_raw)
                    role_name = (str(role_name_raw).strip() if role_name_raw else None)
                    level_req = _to_int_or_none(level_raw)
                    msgs_req = _to_int_or_none(msgs_req_raw)

                    if not ended:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Das Gewinnspiel läuft noch!**", ephemeral=True)
                        return

                    channel = interaction.guild.get_channel(int(channelID))
                    msg = await channel.fetch_message(int(messageid))

                    await cur.execute(
                        "SELECT userID FROM giveaway_entrys WHERE messageID = %s AND guildID = %s AND channelID = %s",
                        (int(messageid), interaction.guild.id, channelID),
                    )
                    result2 = await cur.fetchall()

                    raw_user_ids = [row[0] for row in result2]
                    valid_ids: list[int] = []
                    for uid in raw_user_ids:
                        member = interaction.guild.get_member(int(uid))
                        if not member:
                            continue
                        ok = True
                        if role_id is not None:
                            r = interaction.guild.get_role(role_id)
                            if not r or r not in member.roles:
                                ok = False
                        if ok and level_req is not None:
                            await cur.execute(
                                "SELECT user_level FROM levelsystem WHERE client_id = %s AND guild_id = %s",
                                (member.id, interaction.guild.id),
                            )
                            row_lvl = await cur.fetchone()
                            have_level = int(row_lvl[0]) if row_lvl and row_lvl[0] is not None else 0
                            if have_level < level_req:
                                ok = False
                        if ok and msgs_req is not None:
                            await cur.execute(
                                "SELECT count FROM user_message_counts WHERE guildID = %s AND userID = %s",
                                (interaction.guild.id, member.id),
                            )
                            row_msg = await cur.fetchone()
                            have_msgs = int(row_msg[0]) if row_msg and row_msg[0] is not None else 0
                            if have_msgs < msgs_req:
                                ok = False
                        if ok:
                            valid_ids.append(int(uid))

                    winners_count = min(len(valid_ids), int(winners))
                    if winners_count < 1:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> **Das Gewinnspiel konnte nicht neu ausgelost werden, da es keine gültigen Teilnehmer gab.**",
                            ephemeral=True,
                        )
                        return

                    winners_ids = random.sample(valid_ids, k=winners_count)
                    users = [self.bot.get_user(uid) for uid in winners_ids]
                    mentions = ", ".join(u.mention for u in users if u)

                    end_dt = datetime.fromtimestamp(int(end_time), tz=timezone.utc)
                    for u in users:
                        if u:
                            win = discord.Embed(
                                title=" ",
                                description=(
                                    f"🏆 Preis: {preis}\n"
                                    "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                                    f"`🎉` Du hast ein Gewinnspiel auf [{interaction.guild.name}](https://discord.com/channels/{interaction.guild.id}/{channel.id}/{msg.id}) gewonnen.\n"
                                    f"`⏰` Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}"
                                ),
                                colour=discord.Colour.yellow(),
                            )
                            if interaction.guild.icon:
                                win.set_thumbnail(url=interaction.guild.icon.url)
                            try:
                                await u.send("<:Astra_herz:1141303857855594527> **Du hast ein Gewinnspiel gewonnen! Herzlichen Glückwunsch.**", embed=win)
                            except Exception:
                                pass

                    embed = discord.Embed(
                        title=" ",
                        description=(
                            f"🏆 Preis: {preis}\n"
                            "`🤖` [Astra Einladen](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n\n"
                            "<:Astra_gw_open2:1061384624951021578> » __**Wer hat das Gewinnspiel gewonnen?**__\n"
                            f"<:Astra_arrow:1141303823600717885> {mentions} hat das Gewinnspiel gewonnen.\n"
                            f"<:Astra_arrow:1141303823600717885> Das Gewinnspiel endete {discord.utils.format_dt(end_dt, 'R')}\n"
                            f"<:Astra_arrow:1141303823600717885> Es gab **{entrys}** Teilnehmer."
                        ),
                        colour=discord.Colour.red(),
                    )
                    await msg.edit(content="`❌` Gewinnspiel Vorbei `❌`", embed=embed, view=None)
                    await msg.reply(f"<:Astra_gw1:1141303852889550928> {mentions} hat das Gewinnspiel gewonnen. Herzlichen Glückwunsch.")

                    await interaction.response.send_message(
                        f"<:Astra_accept:1141303821176422460> **Ich habe das Gewinnspiel neu ausgelost, die neuen Gewinner sind {mentions}.**",
                        ephemeral=True,
                    )


# --------------------------- Message Counter ---------------------------
class MessageCounterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> (has_active, expires_at)
        self._active_giveaway_cache: dict[int, tuple[bool, datetime]] = {}
        self._cache_ttl = timedelta(seconds=60)  # nur DB-Entlastung

    async def _has_active_giveaway(self, cur, guild_id: int) -> bool:
        now = datetime.now(timezone.utc)
        cached = self._active_giveaway_cache.get(guild_id)
        if cached and cached[1] > now:
            return cached[0]

        await cur.execute("SELECT 1 FROM giveaway_active WHERE guildID = %s AND ended = 0 LIMIT 1", (guild_id,))
        row = await cur.fetchone()
        has_active = bool(row)
        self._active_giveaway_cache[guild_id] = (has_active, now + self._cache_ttl)
        return has_active

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if not msg.guild or msg.author.bot:
            return
        try:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    if not await self._has_active_giveaway(cur, msg.guild.id):
                        return
                    await cur.execute(
                        "INSERT INTO user_message_counts (guildID, userID, count) "
                        "VALUES (%s, %s, 1) "
                        "ON DUPLICATE KEY UPDATE count = count + 1",
                        (msg.guild.id, msg.author.id),
                    )
        except Exception:
            # leise scheitern
            pass


# ------------------------------ Setup ------------------------------
async def setup(bot: commands.Bot):
    bot.add_view(GiveawayButton(bot))  # persistente View
    await bot.add_cog(MessageCounterCog(bot))
    try:
        bot.tree.remove_command("gewinnspiel", type=discord.AppCommandType.chat_input)
    except Exception:
        pass
    bot.tree.add_command(Giveaway(bot))
