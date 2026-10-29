import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import asyncio
import logging
from dateutil import tz
import re
from datetime import datetime, timedelta, timezone
import time

GOAL_TYPES = {
    "messages": ("Nachrichten", "💬"),
    "voice_minutes": ("Voice-Minuten", "🔊"),
    "xp": ("XP", "✨"),
    "levelups": ("Level-Ups", "⬆️"),
    "new_users": ("Neue User", "👤"),
    "ban_free": ("Ban-freie Tage", "🕊️"),
    "commands_used": ("Befehle genutzt", "⚡"),
}

def parse_time_input(time_str: str) -> Optional[int]:
    now = datetime.now(timezone.utc)
    local_zone = tz.tzlocal()
    if re.fullmatch(r"\d{1,2}", time_str):
        tage = int(time_str)
        if 1 <= tage <= 60:
            return int((now + timedelta(days=tage)).timestamp())
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2})(?::(\d{1,2}))?)?", time_str)
    if m:
        tag, monat, jahr = int(m[1]), int(m[2]), int(m[3])
        stunde = int(m[4]) if m[4] else 0
        minute = int(m[5]) if m[5] else 0
        try:
            dt_local = datetime(jahr, monat, tag, stunde, minute, tzinfo=local_zone)
            dt_utc = dt_local.astimezone(timezone.utc)
            if dt_utc.timestamp() > now.timestamp():
                return int(dt_utc.timestamp())
        except Exception:
            return None
    m = re.fullmatch(r"(\d{1,2})(?::(\d{1,2}))?", time_str)
    if m:
        stunde = int(m[1])
        minute = int(m[2]) if m[2] else 0
        try:
            now_local = datetime.now(local_zone)
            dt_local = now_local.replace(hour=stunde, minute=minute, second=0, microsecond=0)
            if dt_local.timestamp() <= now_local.timestamp():
                dt_local += timedelta(days=1)
            return int(dt_local.astimezone(timezone.utc).timestamp())
        except Exception:
            return None
    return None

def format_goal_embed(conds, reward_text, ends_at_ts, finished, total, reward_role=None, status=None):
    sum_percent = 0
    cond_lines = []
    for typ, target, value in conds:
        percent = min(1.0, value / target if target > 0 else 0)
        sum_percent += percent
        icon, name = GOAL_TYPES.get(typ, ("???", "❓"))
        cond_lines.append(f"{icon} **{name}:** {value:,} / {target:,}")
    avg_percent = sum_percent / len(conds) if conds else 0
    bar_blocks = 20
    filled = int(avg_percent * bar_blocks)
    empty = bar_blocks - filled
    bar = f"[{'█'*filled}{'–'*empty}] {avg_percent*100:4.1f}%"
    embed = discord.Embed(
        title=status or "🎯 Community Goal Status",
        description=f"Läuft bis <t:{ends_at_ts}:f>\n\n"
                    + "\n".join(cond_lines)
                    + "\n\n__**Fortschritt insgesamt:**__\n"
                    + bar,
        color=discord.Color.blurple() if not status else (discord.Color.green() if "GESCHAFFT" in status else discord.Color.red())
    )
    if reward_text or reward_role:
        val = reward_text or "*Keine Belohnung angegeben*"
        if reward_role and (not reward_text or reward_role.mention not in reward_text):
            val += f"\n{reward_role.mention}"
        embed.add_field(name="🎁 Belohnung", value=val, inline=False)
    return embed

# --- BUTTON/MODAL FLOW IMPLEMENTATION wie gehabt ---

class GoalSetupState:
    def __init__(self, interaction: discord.Interaction, ziel_kanal, reward_role, data_page1):
        self.interaction = interaction
        self.ziel_kanal = ziel_kanal
        self.reward_role = reward_role
        self.data_page1 = data_page1
        self.message = None

class WeiterButton(discord.ui.View):
    def __init__(self, setup_state: GoalSetupState):
        super().__init__(timeout=300)
        self.setup_state = setup_state

    @discord.ui.button(label="Weiter", style=discord.ButtonStyle.primary)
    async def weiter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.setup_state.interaction.user:
            return await interaction.response.send_message("Nur der Ersteller kann fortfahren.", ephemeral=True)
        await interaction.response.send_modal(GoalModalPage2(self.setup_state))
        return None


class FertigButton(discord.ui.View):
    def __init__(self, setup_state: GoalSetupState, cond_lines, ends_ts, belohnung_text):
        super().__init__(timeout=300)
        self.setup_state = setup_state
        self.cond_lines = cond_lines
        self.ends_ts = ends_ts
        self.belohnung_text = belohnung_text

    @discord.ui.button(label="Fertig", style=discord.ButtonStyle.success)
    async def fertig(self, interaction: discord.Interaction, button: discord.ui.Button):
        await CommunityGoalsGroup.create_goal_from_modal(
            {**self.setup_state.data_page1, **self.setup_state.data_page2},
            self.setup_state.ziel_kanal,
            interaction,
            self.setup_state.reward_role
        )
        # **View nach Klick deaktivieren**
        try:
            await interaction.response.edit_message(view=None)
        except Exception:
            pass
class GoalModalPage1(discord.ui.Modal, title="Community Goal erstellen (1/2)"):
    dauer = discord.ui.TextInput(label="Ende (Tage, Datum oder Uhrzeit)", required=True, placeholder="z.B. 14 oder 05.08.2025 18:00 oder 18:00")
    belohnung_text = discord.ui.TextInput(label="Belohnung (optional, Text)", required=False, placeholder="Text, z.B. '500 Coins'")
    nachrichten = discord.ui.TextInput(label="Nachrichten-Ziel (optional)", required=False, placeholder="z.B. 2500")
    voice_minuten = discord.ui.TextInput(label="Voice-Minuten-Ziel (optional)", required=False, placeholder="z.B. 1000")
    xp = discord.ui.TextInput(label="XP-Ziel (optional)", required=False, placeholder="z.B. 25000")

    def __init__(self, ziel_kanal: discord.TextChannel, reward_role: Optional[discord.Role]):
        super().__init__()
        self.ziel_kanal = ziel_kanal
        self.reward_role = reward_role

    async def on_submit(self, interaction: discord.Interaction):
        data_page1 = {
            "dauer": self.dauer.value.strip(),
            "belohnung_text": self.belohnung_text.value.strip(),
            "nachrichten": self.nachrichten.value.strip(),
            "voice_minuten": self.voice_minuten.value.strip(),
            "xp": self.xp.value.strip(),
        }

        ends_ts = parse_time_input(data_page1["dauer"])
        if not ends_ts or ends_ts <= int(time.time()):
            return await interaction.response.send_message("Ungültiges Enddatum.", ephemeral=True)

        cond_lines = []
        if data_page1["nachrichten"]:
            cond_lines.append(
                f"{GOAL_TYPES['messages'][1]} **{GOAL_TYPES['messages'][0]}:** {int(data_page1['nachrichten']):,}")
        if data_page1["voice_minuten"]:
            cond_lines.append(
                f"{GOAL_TYPES['voice_minutes'][1]} **{GOAL_TYPES['voice_minutes'][0]}:** {int(data_page1['voice_minuten']):,}")
        if data_page1["xp"]:
            cond_lines.append(f"{GOAL_TYPES['xp'][1]} **{GOAL_TYPES['xp'][0]}:** {int(data_page1['xp']):,}")

        embed = discord.Embed(
            title="📋 Zielübersicht (1/2)",
            description=f"**Ende:** <t:{ends_ts}:f>\n\n" + (
                "\n".join(cond_lines) if cond_lines else "*Noch kein Ziel angegeben*"),
            color=discord.Color.blurple()
        )
        if data_page1["belohnung_text"]:
            embed.add_field(name="🏱 Belohnung", value=data_page1["belohnung_text"], inline=False)

        setup_state = GoalSetupState(interaction, self.ziel_kanal, self.reward_role, data_page1)
        await interaction.response.send_message(embed=embed, view=WeiterButton(setup_state), ephemeral=True)
        return None


class GoalModalPage2(discord.ui.Modal, title="Community Goal erstellen (2/2)"):
    levelups = discord.ui.TextInput(label="Level-Ups-Ziel (optional)", required=False, placeholder="z.B. 15")
    neue_mitglieder = discord.ui.TextInput(label="Neue Mitglieder-Ziel (optional)", required=False, placeholder="z.B. 12")
    banfrei = discord.ui.TextInput(label="Ban-freie Tage (optional)", required=False, placeholder="z.B. 14")
    befehle = discord.ui.TextInput(label="Befehle genutzt-Ziel (optional)", required=False, placeholder="z.B. 200")

    def __init__(self, setup_state: GoalSetupState):
        super().__init__()
        self.setup_state = setup_state

    async def on_submit(self, interaction: discord.Interaction):
        data_page2 = {
            "levelups": self.levelups.value.strip(),
            "neue_mitglieder": self.neue_mitglieder.value.strip(),
            "banfrei": self.banfrei.value.strip(),
            "befehle": self.befehle.value.strip(),
        }
        self.setup_state.data_page2 = data_page2

        full_data = {**self.setup_state.data_page1, **data_page2}

        def to_int(s):
            return int(s.replace(".", "").replace(",", "")) if s else None

        mapping = [
            ("messages", to_int(full_data.get("nachrichten"))),
            ("voice_minutes", to_int(full_data.get("voice_minuten"))),
            ("xp", to_int(full_data.get("xp"))),
            ("levelups", to_int(full_data.get("levelups"))),
            ("new_users", to_int(full_data.get("neue_mitglieder"))),
            ("ban_free", to_int(full_data.get("banfrei"))),
            ("commands_used", to_int(full_data.get("befehle"))),
        ]
        conds = [(typ, val) for typ, val in mapping if val and val > 0]
        if not conds:
            return await interaction.response.send_message("Du musst mindestens eine Bedingung ausfüllen!",
                                                           ephemeral=True)

        # (Rest wie gehabt, optional das Embed-Preview)
        ends_ts = parse_time_input(full_data["dauer"])
        cond_lines = "\n".join(f"{GOAL_TYPES[typ][1]} **{GOAL_TYPES[typ][0]}:** {val:,}" for typ, val in conds)

        embed = discord.Embed(
            title="📋 Zielübersicht (komplett)",
            description=f"**Ende:** <t:{ends_ts}:f>\n\n{cond_lines}",
            color=discord.Color.green()
        )
        reward_text = full_data.get("belohnung_text")
        if reward_text:
            embed.add_field(name="🏱 Belohnung", value=reward_text, inline=False)

        await interaction.response.edit_message(embed=embed, view=FertigButton(self.setup_state, cond_lines, ends_ts, reward_text))

@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_events=True)
class CommunityGoalsGroup(app_commands.Group):
    def __init__(self, cog):
        super().__init__(name="communitygoals", description="Communityziele!")
        self.cog = cog

    @app_commands.command(name="erstellen", description="Setzt ein neues Communityziel via Modal.")
    @app_commands.describe(
        channel="Channel für das Ziel-Embed & Updates.",
        belohnung_rolle="Optionale Rolle als Belohnung"
    )
    @app_commands.checks.has_permissions(manage_events=True)
    async def erstellen(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        belohnung_rolle: Optional[discord.Role] = None
    ):
        await interaction.response.send_modal(GoalModalPage1(channel, belohnung_rolle))

    @staticmethod
    async def create_goal_from_modal(goal_data, channel, interaction: discord.Interaction,
                                     reward_role: Optional[discord.Role] = None):
        now_ts = int(time.time())
        ends_raw = goal_data.get("dauer", "")
        ends_ts = parse_time_input(ends_raw)
        if not ends_ts or ends_ts <= now_ts:
            try:
                await interaction.response.send_message(
                    "Ungültiges oder vergangenes Enddatum. Bitte gib einen gültigen Wert an.", ephemeral=True)
            except discord.InteractionResponded:
                pass
            return

        belohnung_text = goal_data.get("belohnung_text") or None

        def to_int(s):
            try:
                return int(s.replace(".", "").replace(",", "")) if s else None
            except Exception:
                return None

        nachrichten = to_int(goal_data.get("nachrichten"))
        voice_minuten = to_int(goal_data.get("voice_minuten"))
        xp = to_int(goal_data.get("xp"))
        levelups = to_int(goal_data.get("levelups"))
        neue_mitglieder = to_int(goal_data.get("neue_mitglieder"))
        banfrei = to_int(goal_data.get("banfrei"))
        befehle = to_int(goal_data.get("befehle"))

        conds = []
        mapping = [
            ("messages", nachrichten),
            ("voice_minutes", voice_minuten),
            ("xp", xp),
            ("levelups", levelups),
            ("new_users", neue_mitglieder),
            ("ban_free", banfrei),
            ("commands_used", befehle),
        ]
        for key, val in mapping:
            if val is not None and val > 0:
                conds.append((key, val))
        if not conds:
            embed = discord.Embed(
                title="🚫 Fehler",
                description="Mindestens eine Bedingung mit Wert > 0 angeben.",
                color=discord.Color.red()
            )
            try:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.InteractionResponded:
                pass
            return

        embed = format_goal_embed(
            [(typ, val, 0) for typ, val in conds],
            belohnung_text,
            ends_ts,
            0,
            len(conds),
            reward_role=reward_role
        )

        goal_message = await channel.send(embed=embed)
        msg_id = goal_message.id
        ziel_kanal_id = channel.id

        async with interaction.client.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE community_goals SET active=FALSE WHERE guild_id=%s", (interaction.guild.id,))
                await cur.execute(
                    "INSERT INTO community_goals (guild_id, started_at, ends_at, reward_role_id, reward_text, active, channel_id, msg_id) VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)",
                    (interaction.guild.id, now_ts, ends_ts, reward_role.id if reward_role else None, belohnung_text,
                     ziel_kanal_id, msg_id)
                )
                if hasattr(cur, "lastrowid"):
                    goal_id = cur.lastrowid
                else:
                    await cur.execute("SELECT LAST_INSERT_ID()")
                    goal_id = (await cur.fetchone())[0]
                for typ, val in conds:
                    await cur.execute(
                        "INSERT INTO community_goal_conditions (goal_id, type, target, progress) VALUES (%s, %s, %s, 0)",
                        (goal_id, typ, val)
                    )
                await conn.commit()

        # Starte Task für Auto-Update!
        interaction.client.loop.create_task(
            interaction.client.get_cog("CommunityGoalsCog").goal_auto_update_task(
                goal_id, interaction.guild.id, ends_ts, reward_role.id if reward_role else None
            )
        )

        try:
            await interaction.response.send_message(
                f"Community Goal wurde erstellt und im Channel {channel.mention} gepostet!", ephemeral=True
            )
        except discord.InteractionResponded:
            pass

    @app_commands.command(name="status", description="Zeigt das aktuelle Communityziel und den Fortschritt.")
    @app_commands.checks.has_permissions(manage_events=True)
    async def status(self, interaction: discord.Interaction):
        async with self.cog.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, reward_role_id, reward_text, ends_at FROM community_goals WHERE guild_id=%s AND active=TRUE LIMIT 1",
                    (interaction.guild.id,)
                )
                goal = await cur.fetchone()
                if not goal:
                    embed = discord.Embed(
                        title="🚫 Kein aktives Community Goal",
                        description="Momentan läuft kein Ziel. Erstelle eines mit /communitygoals erstellen.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                goal_id, reward_role_id, reward_text, ends_at_ts = goal
                reward_role = interaction.guild.get_role(reward_role_id) if reward_role_id else None

                await cur.execute("SELECT type, target, progress FROM community_goal_conditions WHERE goal_id=%s", (goal_id,))
                conds_db = await cur.fetchall()

                conds = []
                finished = 0
                for typ, target, progress in conds_db:
                    value = min(progress, target)
                    if typ == "xp":
                        await cur.execute("SELECT SUM(user_xp) FROM levelsystem WHERE guild_id=%s", (interaction.guild.id,))
                        sum_xp = await cur.fetchone()
                        value = min(sum_xp[0] or 0, target)
                    elif typ == "new_users":
                        value = min(interaction.guild.member_count, target)
                    if value >= target:
                        finished += 1
                    conds.append((typ, target, value))

                embed = format_goal_embed(conds, reward_text, ends_at_ts, finished, len(conds), reward_role, status=None)
                await interaction.response.send_message(embed=embed, ephemeral=True)

# ---- CommunityGoalsCog wie gehabt, aber jetzt mit automatischem Embed-Update ----

class CommunityGoalsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_time = {}
        self.goal_tasks_started = False
        bot.loop.create_task(self.schedule_goal_end_tasks())

    async def announce_and_check_goal(self, guild_id):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, channel_id, msg_id, reward_role_id, reward_text, ends_at FROM community_goals WHERE guild_id=%s AND active=TRUE LIMIT 1",
                    (guild_id,)
                )
                goal = await cur.fetchone()
                if not goal:
                    return
                goal_id, channel_id, msg_id, reward_role_id, reward_text, ends_at_ts = goal
                guild = self.bot.get_guild(guild_id)
                reward_role = guild.get_role(reward_role_id) if reward_role_id else None
                channel = guild.get_channel(channel_id) if guild else None
                if not channel:
                    return
                try:
                    msg = await channel.fetch_message(msg_id)
                except Exception:
                    return

                # Nachricht-IDs für spätere Löschung speichern (RAM-Safe)
                if not hasattr(self, "announce_message_ids"):
                    self.announce_message_ids = {}
                ids = self.announce_message_ids.setdefault(goal_id, [])

                # Ziele prüfen
                await cur.execute(
                    "SELECT type, target, progress, announced FROM community_goal_conditions WHERE goal_id=%s",
                    (goal_id,)
                )
                conds_db = await cur.fetchall()
                conds = []
                finished = 0
                announce_types = []
                for typ, target, progress, announced in conds_db:
                    value = min(progress, target)
                    if typ == "xp":
                        await cur.execute("SELECT SUM(user_xp) FROM levelsystem WHERE guild_id=%s", (guild_id,))
                        sum_xp = await cur.fetchone()
                        value = min(sum_xp[0] or 0, target)
                    elif typ == "new_users":
                        value = min(guild.member_count, target) if guild else 0
                    if value >= target:
                        finished += 1
                    conds.append((typ, target, value))
                    if value >= target and not announced:
                        announce_types.append(typ)

                # Einzeln erfüllte Ziele ansagen
                for typ in announce_types:
                    icon, name = GOAL_TYPES.get(typ, ("???", "❓"))
                    announce_msg = await channel.send(f"🎉 Das Ziel **{icon} {name}** wurde erfüllt!")
                    ids.append(announce_msg.id)
                    await cur.execute(
                        "UPDATE community_goal_conditions SET announced=TRUE WHERE goal_id=%s AND type=%s",
                        (goal_id, typ)
                    )
                await conn.commit()

                # Prüfen ob ALLE fertig
                all_done = finished == len(conds) and finished > 0
                if all_done:
                    # Alte Einzel-Nachrichten löschen!
                    for mid in ids:
                        try:
                            del_msg = await channel.fetch_message(mid)
                            await del_msg.delete()
                        except Exception:
                            pass
                    self.announce_message_ids[goal_id] = []

                    # Gesamterfolg-Message schicken
                    done_msg = await channel.send("🎊 **Alle Community-Ziele wurden erreicht! Glückwunsch an alle!** 🎊")

                    # Rolle verteilen
                    if reward_role:
                        for member in guild.members:
                            try:
                                await member.add_roles(reward_role, reason="Community Goal abgeschlossen")
                            except Exception:
                                pass

                    # Embed aktualisieren
                    embed = format_goal_embed(
                        conds, reward_text, ends_at_ts, finished, len(conds), reward_role,
                        status="🏁 Community Goal **GESCHAFFT!**"
                    )
                    embed.description = "Alle Ziele wurden erreicht! 🎉"
                    try:
                        await msg.edit(embed=embed)
                    except Exception:
                        pass
                else:
                    # Nur Embed updaten, falls nicht alles fertig
                    embed = format_goal_embed(conds, reward_text, ends_at_ts, finished, len(conds), reward_role)
                    try:
                        await msg.edit(embed=embed)
                    except Exception:
                        pass

    async def schedule_goal_end_tasks(self):
        await self.bot.wait_until_ready()
        if self.goal_tasks_started:
            return
        self.goal_tasks_started = True
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, guild_id, ends_at, reward_role_id FROM community_goals WHERE active=TRUE AND ends_at > %s",
                    (int(time.time()),)
                )
                entries = await cur.fetchall()
                for goal_id, guild_id, ends_at, reward_role_id in entries:
                    self.bot.loop.create_task(self.goal_auto_update_task(goal_id, guild_id, ends_at, reward_role_id))

    async def goal_auto_update_task(self, goal_id, guild_id, ends_at_ts, reward_role_id=None):
        try:
            now_ts = int(time.time())
            if ends_at_ts < now_ts:
                ends_at_ts = now_ts

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT channel_id, msg_id, reward_text FROM community_goals WHERE id=%s", (goal_id,))
                    res = await cur.fetchone()
                    if not res:
                        return
                    channel_id, msg_id, reward_text = res

                    guild = self.bot.get_guild(guild_id)
                    channel = None
                    msg = None
                    if guild:
                        channel = guild.get_channel(channel_id)
                        if channel is None:
                            try:
                                channel = await guild.fetch_channel(channel_id)
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                channel = None

                        if channel and isinstance(channel, discord.TextChannel):
                            try:
                                msg = await channel.fetch_message(msg_id)
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                msg = None

                    reward_role = guild.get_role(reward_role_id) if reward_role_id and guild else None

                    # Warten bis Zeit vorbei ist!
                    while True:
                        time_left = ends_at_ts - int(time.time())
                        if time_left > 0:
                            await asyncio.sleep(min(60, time_left))  # jede Minute checken
                            continue

                        # ENDE ERREICHT: Aber prüfe, ob das Ziel schon geschafft ist!
                        await cur.execute("SELECT type, target, progress FROM community_goal_conditions WHERE goal_id=%s",
                                          (goal_id,))
                        conds_db = await cur.fetchall()
                        finished = sum(1 for typ, target, progress in conds_db if progress >= target)
                        conds = [(typ, target, progress) for typ, target, progress in conds_db]

                        all_done = finished == len(conds) and finished > 0

                        if all_done:
                            status = "🏁 Community Goal **GESCHAFFT!**"
                            desc = "Alle Ziele wurden erreicht! 🎉"
                            # Rollenverteilen, falls noch nicht geschehen:
                            if reward_role and guild:
                                for member in guild.members:
                                    try:
                                        await member.add_roles(reward_role, reason="Community Goal abgeschlossen")
                                    except (discord.Forbidden, discord.HTTPException):
                                        pass
                        else:
                            status = "⏹️ Community Goal beendet"
                            desc = f"Nicht alle Ziele wurden erreicht! **{finished}/{len(conds)}**"

                        final_embed = format_goal_embed(
                            conds, reward_text, ends_at_ts, finished, len(conds), reward_role, status=status
                        )
                        final_embed.description = desc
                        if msg:
                            try:
                                await msg.edit(embed=final_embed)
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                pass

                        await cur.execute("UPDATE community_goals SET active=FALSE WHERE id=%s", (goal_id,))
                        await cur.execute("DELETE FROM community_goal_conditions WHERE goal_id=%s", (goal_id,))
                        await cur.execute("DELETE FROM community_goals WHERE id=%s", (goal_id,))
                        await conn.commit()
                        break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.exception(f"[Goals] Fehler im goal_auto_update_task für Goal {goal_id} (Guild {guild_id}): {e}")

    async def check_ban_in_period(self, guild_id, started_at: datetime, ends_at: datetime) -> bool:
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM goal_bans WHERE guild_id=%s AND time BETWEEN %s AND %s LIMIT 1",
                    (guild_id, started_at, ends_at)
                )
                return bool(await cur.fetchone())

    # Listener etc. wie gehabt ...

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, reward_text FROM community_goals WHERE guild_id=%s AND active=TRUE LIMIT 1",
                    (message.guild.id,)
                )
                res = await cur.fetchone()
                if not res:
                    return
                goal_id, reward_text = res

                channel_limit = None
                if reward_text and "CHANNEL:" in reward_text:
                    m = re.search(r"CHANNEL:(\d+)", reward_text)
                    if m:
                        channel_limit = int(m[1])
                if channel_limit and message.channel.id != channel_limit:
                    return

                await cur.execute(
                    "SELECT target, progress FROM community_goal_conditions WHERE goal_id=%s AND type='messages'", (goal_id,)
                )
                cond = await cur.fetchone()
                if cond:
                    target, progress = cond
                    if progress < target:
                        await cur.execute(
                            "UPDATE community_goal_conditions SET progress=LEAST(progress + 1, target) WHERE goal_id=%s AND type='messages'",
                            (goal_id,)
                        )
                        await conn.commit()
                        await self.announce_and_check_goal(message.guild.id)  # <- NEU!

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if not member.guild:
            return
        guild_id = member.guild.id
        user_id = member.id
        now = time.time()
        if after.channel and not before.channel:
            self.voice_time.setdefault(guild_id, {})[user_id] = now
        elif before.channel and not after.channel:
            if guild_id in self.voice_time and user_id in self.voice_time[guild_id]:
                joined_at = self.voice_time[guild_id].pop(user_id)
                minutes = int((now - joined_at) // 60)
                if minutes > 0:
                    async with self.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                SELECT g.id
                                FROM community_goals g
                                JOIN community_goal_conditions c ON g.id = c.goal_id
                                WHERE g.guild_id=%s AND g.active=TRUE AND c.type='voice_minutes'
                                LIMIT 1
                                """,
                                (guild_id,)
                            )
                            goal = await cur.fetchone()
                            if goal:
                                goal_id = goal[0]
                                await cur.execute(
                                    "SELECT target, progress FROM community_goal_conditions WHERE goal_id=%s AND type='voice_minutes'",
                                    (goal_id,)
                                )
                                cond = await cur.fetchone()
                                if cond:
                                    target, progress = cond
                                    if progress < target:
                                        add_minutes = min(minutes, target - progress)
                                        await cur.execute(
                                            "UPDATE community_goal_conditions SET progress=LEAST(progress + %s, target) WHERE goal_id=%s AND type='voice_minutes'",
                                            (add_minutes, goal_id)
                                        )
                                        await conn.commit()
                                        await self.announce_and_check_goal(member.guild.id)  # <- NEU!

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if not interaction.guild or interaction.user.bot:
            return
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT g.id
                    FROM community_goals g
                    JOIN community_goal_conditions c ON g.id = c.goal_id
                    WHERE g.guild_id=%s AND g.active=TRUE AND c.type='commands_used'
                    LIMIT 1
                    """,
                    (interaction.guild.id,)
                )
                goal = await cur.fetchone()
                if goal:
                    goal_id = goal[0]
                    await cur.execute(
                        "SELECT target, progress FROM community_goal_conditions WHERE goal_id=%s AND type='commands_used'",
                        (goal_id,)
                    )
                    cond = await cur.fetchone()
                    if cond:
                        target, progress = cond
                        if progress < target:
                            await cur.execute(
                                "UPDATE community_goal_conditions SET progress=LEAST(progress + 1, target) WHERE goal_id=%s AND type='commands_used'",
                                (goal_id,)
                            )
                            await conn.commit()
                            await self.announce_and_check_goal(interaction.guild.id)  # <- NEU!

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT g.id
                    FROM community_goals g
                    JOIN community_goal_conditions c ON g.id = c.goal_id
                    WHERE g.guild_id=%s AND g.active=TRUE AND c.type='new_users'
                    LIMIT 1
                    """,
                    (member.guild.id,)
                )
                goal = await cur.fetchone()
                if goal:
                    goal_id = goal[0]
                    await cur.execute(
                        "SELECT target, progress FROM community_goal_conditions WHERE goal_id=%s AND type='new_users'",
                        (goal_id,)
                    )
                    cond = await cur.fetchone()
                    if cond:
                        target, progress = cond
                        if progress < target:
                            await cur.execute(
                                "UPDATE community_goal_conditions SET progress=LEAST(progress + 1, target) WHERE goal_id=%s AND type='new_users'",
                                (goal_id,)
                            )
                            await conn.commit()
                            await self.announce_and_check_goal(member.guild.id)  # <- NEU!

    async def count_levelup(self, guild_id):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT g.id
                    FROM community_goals g
                    JOIN community_goal_conditions c ON g.id = c.goal_id
                    WHERE g.guild_id=%s AND g.active=TRUE AND c.type='levelups'
                    LIMIT 1
                    """,
                    (guild_id,)
                )
                goal = await cur.fetchone()
                if goal:
                    goal_id = goal[0]
                    await cur.execute(
                        "SELECT target, progress FROM community_goal_conditions WHERE goal_id=%s AND type='levelups'",
                        (goal_id,)
                    )
                    cond = await cur.fetchone()
                    if cond:
                        target, progress = cond
                        if progress < target:
                            await cur.execute(
                                "UPDATE community_goal_conditions SET progress=LEAST(progress + 1, target) WHERE goal_id=%s AND type='levelups'",
                                (goal_id,)
                            )
                            await conn.commit()
                            await self.announce_and_check_goal(guild_id)  # <- NEU!

async def setup(bot):
    cog = CommunityGoalsCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(CommunityGoalsGroup(cog))
