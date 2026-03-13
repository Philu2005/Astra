import discord
from discord.ext import commands
import subprocess
import textwrap
import traceback
from math import ceil
import sys
import psutil
from discord import app_commands
from collections import defaultdict
import inspect
import io
import asyncio
import time
from typing import List, Optional
import logging
from pathlib import Path
import re

SCHEMA_PATH = "/root/Astra/opt/schema.sql"  # <- Pfad zu deiner Datei

async def run_sql_file(pool, path: str):
    p = Path(path)
    if not p.exists():
        logging.error(f"[DB] SQL-Datei nicht gefunden: {path}")
        return

    raw = p.read_text(encoding="utf-8")

    # -- Kommentare entfernen (-- … und /* … */), dann an ';' splitten
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)          # block comments
    lines = []
    for line in raw.splitlines():
        # entferne Zeilenkommentare, aber nicht in Strings (einfacher Ansatz reicht hier)
        line = re.sub(r"--.*$", "", line)
        lines.append(line)
    cleaned = "\n".join(lines)

    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for stmt in statements:
                try:
                    await cur.execute(stmt)
                except Exception as e:
                    logging.error(f"[DB] Fehler in Statement:\n{stmt}\n{e}")


def resolve_extension(name: str) -> str:
    """
    dev        -> cogs.dev
    cogs.dev   -> cogs.dev
    """
    if "." in name:
        return name
    return f"cogs.{name}"


class CommandLogView(discord.ui.View):
    def __init__(self, ctx, rows, pages):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.rows = rows
        self.pages = pages
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message(
                "Nur der Bot-Owner darf hier klicken.",
                ephemeral=True
            )
            return False
        return True

    def make_embed(self):
        start = self.page * PAGE_SIZE
        end = start + PAGE_SIZE
        chunk = self.rows[start:end]

        embed = discord.Embed(
            title="📊 Command Usage (letzte 7 Tage)",
            color=discord.Color.blurple()
        )

        for guild_id, user_id, cmd, sub, used_at in chunk:
            guild = self.ctx.bot.get_guild(guild_id)
            user = self.ctx.bot.get_user(user_id)

            cmd_name = f"/{cmd}" + (f" {sub}" if sub else "")
            time_str = used_at.strftime("%d.%m.%Y %H:%M:%S")

            embed.add_field(
                name=cmd_name,
                value=(
                    f"👤 **User:** {user} (`{user_id}`)\n"
                    f"🏠 **Server:** {guild.name if guild else guild_id}\n"
                    f"🕒 **Zeit:** `{time_str}`"
                ),
                inline=False
            )

        embed.set_footer(text=f"Seite {self.page + 1}/{self.pages}")
        return embed

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(
                embed=self.make_embed(), view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        if self.page < self.pages - 1:
            self.page += 1
            await interaction.response.edit_message(
                embed=self.make_embed(), view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(label="❌", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _):
        await interaction.message.delete()
        self.stop()

class CmdLogOverviewView(discord.ui.View):
    def __init__(self, ctx, rows):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.rows = rows
        self.pages = ceil(len(rows) / PAGE_SIZE)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Nur der Bot-Owner darf das.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="📄 Vollständiges Log anzeigen",
        style=discord.ButtonStyle.primary
    )
    async def show_full_log(self, interaction: discord.Interaction, _):
        view = CommandLogView(self.ctx, self.rows, self.pages)
        embed = view.make_embed()
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )


# =========================================================
# Helper: Command + Subcommand extrahieren
# =========================================================

def extract_command_path(interaction: discord.Interaction) -> tuple[str, Optional[str]]:
    """
    /levelsystem leaderboard -> ("levelsystem", "leaderboard")
    /ping -> ("ping", None)
    """
    data = interaction.data
    if not data:
        return "unknown", None

    command_name = data.get("name", "unknown")
    subcommand = None

    options = data.get("options")
    if options and options[0].get("type") == 1:  # SUB_COMMAND
        subcommand = options[0].get("name")

    return command_name, subcommand


# =========================================================
# UI: Pagination View (Owner-only)
# =========================================================

class CommandStatsView(discord.ui.View):
    def __init__(self, pages: List[discord.Embed]):
        super().__init__(timeout=180)
        self.pages = pages
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message(
                "Nur der Bot-Owner darf hier interagieren.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(
                embed=self.pages[self.index], view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        if self.index < len(self.pages) - 1:
            self.index += 1
            await interaction.response.edit_message(
                embed=self.pages[self.index], view=self
            )
        else:
            await interaction.response.defer()


# =========================================================
# COG: Command Tracking + Stats
# =========================================================

class CommandTracking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    # -----------------------------------------------------
    # GLOBAL TRACKER (HIER PASSIERT DAS TRACKING)
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.application_command:
            return

        if not interaction.guild:
            return

        command_name, subcommand = extract_command_path(interaction)

        try:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO command_usage
                            (guild_id, user_id, command, subcommand, used_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        """,
                        (
                            interaction.guild.id,
                            interaction.user.id,
                            command_name,
                            subcommand,
                        )
                    )
        except Exception as e:
            print(f"[CommandTracking] DB-Fehler: {e}")

def build_cmdlog_overview_embed(ctx, title: str, rows: list):
    total = len(rows)

    users_count = defaultdict(int)
    guilds_count = defaultdict(int)
    commands_count = defaultdict(int)

    timestamps = []

    for guild_id, user_id, cmd, sub, used_at in rows:
        users_count[user_id] += 1
        guilds_count[guild_id] += 1
        key = f"/{cmd}" + (f" {sub}" if sub else "")
        commands_count[key] += 1
        timestamps.append(used_at)

    start = min(timestamps)
    end = max(timestamps)

    days = max(1, (end - start).days + 1)
    avg_per_day = round(total / days)

    top_commands = sorted(commands_count.items(), key=lambda x: x[1], reverse=True)[:3]
    top_users = sorted(users_count.items(), key=lambda x: x[1], reverse=True)[:3]
    top_guilds = sorted(guilds_count.items(), key=lambda x: x[1], reverse=True)[:3]

    embed = discord.Embed(
        title=title,
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="📈 Übersicht",
        value=(
            f"• **Gesamt-Commands:** `{total}`\n"
            f"• **Ø pro Tag:** `{avg_per_day}`\n"
            f"• **Unterschiedliche Commands:** `{len(commands_count)}`\n"
            f"• **Aktive User:** `{len(users_count)}`\n"
            f"• **Aktive Server:** `{len(guilds_count)}`"
        ),
        inline=False
    )

    embed.add_field(
        name="🔥 Top Commands",
        value="\n".join(
            f"{i+1}. `{cmd}` → **{count}×**"
            for i, (cmd, count) in enumerate(top_commands)
        ) or "—",
        inline=False
    )

    embed.add_field(
        name="👤 Top User",
        value="\n".join(
            f"• <@{uid}> → **{count} Commands**"
            for uid, count in top_users
        ) or "—",
        inline=False
    )

    embed.add_field(
        name="🏠 Top Server",
        value="\n".join(
            f"• **{ctx.bot.get_guild(gid).name if ctx.bot.get_guild(gid) else gid}** → **{count} Commands**"
            for gid, count in top_guilds
        ) or "—",
        inline=False
    )

    embed.add_field(
        name="⏱ Zeitraum",
        value=(
            f"{start.strftime('%d.%m.%Y %H:%M')} → "
            f"{end.strftime('%d.%m.%Y %H:%M')}"
        ),
        inline=False
    )

    embed.set_footer(
        text="Klicke auf „Vollständiges Log“, um alle Einträge zu sehen"
    )

    return embed




PAGE_SIZE = 25  # max. Optionen im Select

def chunk_code_lines(source, chunk_size=1900):
    lines = source.splitlines(keepends=True)
    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) > chunk_size:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks

# ==========
# UI: CodeScroller (persistenzsicher via allowed_user_id)
# ==========
class CodeScroller(discord.ui.View):
    def __init__(self, code_chunks: List[str]):
        super().__init__(timeout=None)
        self.code_chunks = code_chunks
        self.current = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message(
                "Nur Bot Owner dürfen das.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary, custom_id="codescroller_prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current > 0:
            self.current -= 1
            await interaction.response.edit_message(
                content=f"```python\n{self.code_chunks[self.current]}```\nSeite {self.current+1}/{len(self.code_chunks)}",
                view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary, custom_id="codescroller_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current < len(self.code_chunks) - 1:
            self.current += 1
            await interaction.response.edit_message(
                content=f"```python\n{self.code_chunks[self.current]}```\nSeite {self.current+1}/{len(self.code_chunks)}",
                view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="❌", style=discord.ButtonStyle.danger, row=0, custom_id="codescroller_delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        self.stop()

# ==========
# Helpers für App-Commands finden
# ==========
def find_app_command(bot, name: str):
    """
    Sucht nach einem App-Command (auch Subcommand!), z.B. 'levelsystem rank'
    """
    name = name.replace("/", " ").replace(".", " ").strip().lower()

    def gather(cmd, parent=""):
        results = []
        qn = (parent + " " + cmd.name).strip()
        if hasattr(cmd, "commands") and cmd.commands:
            for sub in cmd.commands:
                results += gather(sub, qn)
        else:
            results.append((qn.lower(), cmd))
        return results

    all_cmds = bot.tree.get_commands()
    commands_flat = []
    for cmd in all_cmds:
        commands_flat += gather(cmd)

    for qname, cmd in commands_flat:
        if qname == name:
            return cmd
    return None

# ==========
# SERVERLIST UI (Dropdown + Paging + Leave-Button)
# ==========
def chunked_guilds(guilds: List[discord.Guild], size: int = PAGE_SIZE):
    for i in range(0, len(guilds), size):
        yield guilds[i:i + size]

def guild_option_label(g: discord.Guild) -> str:
    return f"{g.name[:80]}"

def guild_option_desc(g: discord.Guild) -> str:
    return f"ID: {g.id} • Members: {getattr(g, 'member_count', '?')}"

def build_guild_embed(guild: discord.Guild, requester: discord.abc.User) -> discord.Embed:
    owner = getattr(guild, "owner", None)
    features = ", ".join(sorted(guild.features)) if getattr(guild, "features", None) else "—"
    created = discord.utils.format_dt(guild.created_at, style="F")
    joined = discord.utils.format_dt(guild.me.joined_at, style="F") if guild.me and guild.me.joined_at else "—"
    shard = guild.shard_id if guild.shard_id is not None else "—"

    e = discord.Embed(
        title=f"Server: {guild.name}",
        description=f"**ID:** `{guild.id}`",
        color=discord.Color.blurple()
    )
    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    e.add_field(name="Owner", value=f"{owner.mention if owner else 'Unbekannt'} ({owner.id if owner else '—'})", inline=False)
    e.add_field(name="Mitglieder", value=str(getattr(guild, "member_count", "—")))
    e.add_field(name="Boost-Level", value=str(getattr(guild, "premium_tier", '0')))
    e.add_field(name="Boosts", value=str(getattr(guild, "premium_subscription_count", '0')))
    e.add_field(name="Shard", value=str(shard))
    e.add_field(name="Erstellt am", value=created, inline=False)
    e.add_field(name="Bot beigetreten", value=joined, inline=True)
    e.add_field(name="Verifikationslevel", value=str(guild.verification_level).title(), inline=True)
    e.add_field(name="Features", value=features or "—", inline=False)

    channels_text = sum(isinstance(c, discord.TextChannel) for c in guild.channels)
    channels_voice = sum(isinstance(c, discord.VoiceChannel) for c in guild.channels)
    channels_stage = sum(isinstance(c, discord.StageChannel) for c in guild.channels)
    e.add_field(name="Channels",
                value=f"Text: {channels_text} • Voice: {channels_voice} • Stage: {channels_stage}",
                inline=False)

    roles = len(guild.roles)
    emojis = len(guild.emojis)
    e.add_field(name="Rollen", value=str(roles))
    e.add_field(name="Emojis", value=str(emojis))

    e.set_footer(text=f"Angefragt von {requester}", icon_url=requester.display_avatar.url)
    return e


class GuildSelect(discord.ui.Select):
    def __init__(self, page_index: int, page_guilds: List[discord.Guild]):
        options = [
            discord.SelectOption(
                label=guild_option_label(g),
                value=str(g.id),
                description=guild_option_desc(g)[:100]
            )
            for g in page_guilds
        ]
        super().__init__(
            placeholder=f"Server auf Seite {page_index + 1} auswählen…",
            min_values=1, max_values=1,
            options=options
        )
        self.page_index = page_index

    async def callback(self, interaction: discord.Interaction):
        view: ServerListView = self.view  # type: ignore
        if not await view.check_owner(interaction):
            return
        guild_id = int(self.values[0])
        guild = interaction.client.get_guild(guild_id)
        if guild is None:
            await interaction.response.send_message("Konnte den Server nicht finden.", ephemeral=True)
            return
        view.current_guild_id = guild_id
        embed = build_guild_embed(guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=view)


class ConfirmLeaveView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=30)
        self.guild = guild
        self.value: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            await interaction.response.send_message("Nur der Bot-Owner darf das.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ja, Server verlassen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


class ServerListView(discord.ui.View):
    def __init__(self, bot: commands.Bot, requester: discord.abc.User):
        super().__init__(timeout=180)
        self.bot = bot
        self.requester = requester
        self.pages: List[List[discord.Guild]] = list(chunked_guilds(sorted(bot.guilds, key=lambda g: g.name.lower())))
        if not self.pages:
            self.pages = [[]]
        self.page_index: int = 0
        self.current_guild_id: Optional[int] = self.pages[0][0].id if self.pages[0] else None
        self._rebuild_children()

    async def check_owner(self, interaction: discord.Interaction) -> bool:
        try:
            is_owner = await self.bot.is_owner(interaction.user)
        except Exception:
            is_owner = False
        if not is_owner:
            await interaction.response.send_message("Nur der Bot-Owner darf das.", ephemeral=True)
            return False
        return True

    def _rebuild_children(self):
        self.clear_items()

        current_page_guilds = self.pages[self.page_index]
        self.add_item(GuildSelect(self.page_index, current_page_guilds))

        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.leave_button)

        page_label = discord.ui.Button(
            label=f"Seite {self.page_index + 1}/{len(self.pages)}",
            style=discord.ButtonStyle.secondary,
            disabled=True
        )
        self.add_item(page_label)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner(interaction):
            return
        if self.page_index > 0:
            self.page_index -= 1
            if self.pages[self.page_index]:
                self.current_guild_id = self.pages[self.page_index][0].id
        self._rebuild_children()

        guild = interaction.client.get_guild(self.current_guild_id) if self.current_guild_id else None
        embed = build_guild_embed(guild, interaction.user) if guild else discord.Embed(
            title="Keine Server auf dieser Seite", color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner(interaction):
            return
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
            if self.pages[self.page_index]:
                self.current_guild_id = self.pages[self.page_index][0].id
        self._rebuild_children()

        guild = interaction.client.get_guild(self.current_guild_id) if self.current_guild_id else None
        embed = build_guild_embed(guild, interaction.user) if guild else discord.Embed(
            title="Keine Server auf dieser Seite", color=discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Server verlassen", style=discord.ButtonStyle.danger)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner(interaction):
            return
        if not self.current_guild_id:
            await interaction.response.send_message("Bitte zuerst einen Server auswählen.", ephemeral=True)
            return
        guild = interaction.client.get_guild(self.current_guild_id)
        if guild is None:
            await interaction.response.send_message("Konnte den Server nicht finden.", ephemeral=True)
            return

        confirm_view = ConfirmLeaveView(guild)
        confirm_embed = discord.Embed(
            title="Server verlassen?",
            description=f"Soll der Bot **{guild.name}** (ID `{guild.id}`) wirklich verlassen?",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)
        await confirm_view.wait()

        if confirm_view.value is True:
            try:
                await guild.leave()
                # Liste aktualisieren
                self.pages = list(chunked_guilds(sorted(self.bot.guilds, key=lambda g: g.name.lower())))
                if not self.pages:
                    self.pages = [[]]
                self.page_index = min(self.page_index, max(0, len(self.pages) - 1))
                self.current_guild_id = self.pages[self.page_index][0].id if self.pages[self.page_index] else None
                self._rebuild_children()

                new_embed = discord.Embed(
                    title="Bot hat den Server verlassen",
                    description=f"**{guild.name}** (`{guild.id}`)",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=new_embed, ephemeral=True)

                msg_embed = discord.Embed(title="Kein Server ausgewählt", color=discord.Color.blurple())
                if self.current_guild_id:
                    current = self.bot.get_guild(self.current_guild_id)
                    if current:
                        msg_embed = build_guild_embed(current, self.requester)

                try:
                    await interaction.message.edit(embed=msg_embed, view=self)  # type: ignore
                except Exception:
                    pass

            except discord.Forbidden:
                await interaction.followup.send("Keine Berechtigung, den Server zu verlassen.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Fehler: {e}", ephemeral=True)
        else:
            await interaction.followup.send("Abgebrochen.", ephemeral=True)

# ==========
# DEVTOOLS COG (mit integriertem serverlist)
# ==========
class DevTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.commands_run = 0
        self.pool = None  # Pool-Objekt hier zentral gespeichert

    def format_output(self, output):
        if len(output) > 1900:
            return output[:1900] + "\n... (Ausgabe gekürzt)"
        return output

    @commands.command(name="cmdlog")
    @commands.is_owner()
    async def cmdlog(self, ctx: commands.Context, period: str = "today"):
        logging.info("TEST")
        period = period.lower()

        if period in ("week", "woche", "7"):
            title = "📊 Command Usage – letzte 7 Tage"
            where_clause = "used_at >= NOW() - INTERVAL 7 DAY"

        elif period.isdigit():
            days = int(period)
            title = f"📊 Command Usage – letzte {days} Tage"
            where_clause = f"used_at >= NOW() - INTERVAL {days} DAY"

        else:
            title = "📊 Command Usage – heute"
            where_clause = "DATE(used_at) = CURDATE()"

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT guild_id, user_id, command, subcommand, used_at
                    FROM command_usage
                    WHERE {where_clause}
                    ORDER BY used_at DESC
                    """
                )
                rows = await cur.fetchall()

        if not rows:
            await ctx.send("Keine Command-Daten für diesen Zeitraum gefunden.")
            return

        embed = build_cmdlog_overview_embed(ctx, title, rows)
        view = CmdLogOverviewView(ctx, rows)

        await ctx.send(embed=embed, view=view)

    @commands.command(name="commandstats", aliases=["cmdstats"])
    @commands.is_owner()
    async def commandstats(self, ctx: commands.Context):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT command, subcommand, COUNT(*) AS uses
                    FROM command_usage
                    GROUP BY command, subcommand
                    ORDER BY uses DESC
                    """
                )
                rows = await cur.fetchall()

        if not rows:
            await ctx.send("Noch keine Command-Statistiken vorhanden.")
            return

        # -----------------------------
        # Daten strukturieren
        # -----------------------------
        stats = defaultdict(lambda: {"total": 0, "subs": []})
        for command, sub, uses in rows:
            stats[command]["total"] += uses
            stats[command]["subs"].append((sub, uses))

        total_uses = sum(v["total"] for v in stats.values())
        unique_commands = len(stats)

        items = list(stats.items())
        PAGE_SIZE = 5
        pages: List[discord.Embed] = []

        for i in range(0, len(items), PAGE_SIZE):
            embed = discord.Embed(
                title="📊 Command Usage Statistik",
                description=(
                    f"**Gesamtausführungen:** `{total_uses}`\n"
                    f"**Unterschiedliche Commands:** `{unique_commands}`\n"
                    f"**Uptime:** `{int((time.time() - self.start_time) // 60)} min`\n\n"
                    "_Automatisch getrackt (Slash Commands + Subcommands)_"
                ),
                color=discord.Color.blurple()
            )

            for command, data in items[i:i + PAGE_SIZE]:
                lines = []
                for sub, uses in sorted(
                        data["subs"], key=lambda x: x[1], reverse=True
                ):
                    if sub:
                        lines.append(f"• `{sub}` → **{uses}x**")
                    else:
                        lines.append(f"• *(ohne Subcommand)* → **{uses}x**")

                value = f"**Gesamt:** {data['total']}x\n" + "\n".join(lines)
                if len(value) > 1024:
                    value = value[:1000] + "\n…"

                embed.add_field(
                    name=f"/{command}",
                    value=value,
                    inline=False
                )

            embed.set_footer(
                text=(
                    f"Seite {i // PAGE_SIZE + 1}/"
                    f"{(len(items) - 1) // PAGE_SIZE + 1} • "
                    f"Bot-Owner: {ctx.author}"
                )
            )
            pages.append(embed)

        view = CommandStatsView(pages)
        await ctx.send(embed=pages[0], view=view)

    # --- Serverliste (NEU) ---
    @commands.hybrid_command(name="serverlist", aliases=["servers"])
    @commands.is_owner()
    async def serverlist(self, ctx: commands.Context):
        """Zeigt alle Server mit Dropdown, Paging und Leave-Button (nur Owner)."""
        if not self.bot.guilds:
            await ctx.reply("Ich bin in keinen Servern.")
            return

        view = ServerListView(self.bot, requester=ctx.author)
        # sinnvollen Default für das Embed wählen
        first = sorted(self.bot.guilds, key=lambda g: g.name.lower())[0]
        embed = build_guild_embed(first, ctx.author)
        header = "`Select`: Server wählen • ⬅️/➡️: Seite wechseln • 🔴: Server verlassen"
        try:
            await ctx.reply(header, embed=embed, view=view)
        except discord.HTTPException:
            await ctx.reply(embed=embed, view=view)

    @serverlist.error
    async def serverlist_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("Nur der Bot-Owner darf dieses Kommando nutzen.")
        else:
            await ctx.reply(f"Fehler: {error}")

    # --- Eval ---
    @commands.command(name="eval")
    @commands.is_owner()
    async def eval_code(self, ctx, *, code: str):
        """Führt Python-Code aus."""
        self.commands_run += 1
        code = code.strip("` ")
        fn_code = f"async def _eval_fn():\n{textwrap.indent(code, '    ')}"
        env = {
            'bot': self.bot,
            'discord': discord,
            'commands': commands,
            'ctx': ctx,
            'asyncio': asyncio,
            '__import__': __import__
        }
        try:
            exec(fn_code, env)
            result = await env["_eval_fn"]()
            output = repr(result)
        except Exception:
            output = traceback.format_exc()
        await ctx.send(f"```py\n{self.format_output(output)}```")

    @commands.command()
    async def ownercheckall(self, ctx):
        app = await self.bot.application_info()

        if app.team:
            owners = []
            for member in app.team.members:
                if await self.bot.is_owner(member):
                    owners.append(f"{member} ({member.id})")

            await ctx.send("Owner laut is_owner():\n" + "\n".join(owners))

        else:
            await ctx.send(f"Owner: {app.owner} ({app.owner.id})")

    # --- Shell ---
    @commands.command(name="shell")
    @commands.is_owner()
    async def shell_command(self, ctx, *, command: str):
        """Führt Shell-Befehl aus."""
        self.commands_run += 1
        try:
            output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, text=True, timeout=15)
            output = self.format_output(output)
            await ctx.send(f"```bash\n{output}```")
        except subprocess.CalledProcessError as e:
            output = self.format_output(e.output)
            await ctx.send(f"```bash\nFehler:\n{output}```")
        except Exception as e:
            await ctx.send(f"Exception: {e}")

    @commands.group(name="cog", aliases=["ext"], invoke_without_command=True)
    @commands.is_owner()
    async def ext_group(self, ctx: commands.Context):
        await ctx.send(
            "**🧩 Cog-Verwaltung**\n"
            "`astra!cog load <name>`\n"
            "`astra!cog unload <name>`\n"
            "`astra!cog reload <name>`\n"
            "`astra!cog list`"
        )

    @ext_group.command(name="load")
    @commands.is_owner()
    async def ext_load(self, ctx: commands.Context, name: str):
        ext = resolve_extension(name)
        try:
            await self.bot.load_extension(ext)
            await ctx.send(f"✅ Cog `{ext}` geladen.")
        except commands.ExtensionAlreadyLoaded:
            await ctx.send(f"⚠️ Cog `{ext}` ist bereits geladen.")
        except Exception as e:
            await ctx.send(f"❌ Fehler:\n```py\n{e}```")

    @ext_group.command(name="unload")
    @commands.is_owner()
    async def ext_unload(self, ctx: commands.Context, name: str):
        ext = resolve_extension(name)
        try:
            await self.bot.unload_extension(ext)
            await ctx.send(f"🗑️ Cog `{ext}` entladen.")
        except commands.ExtensionNotLoaded:
            await ctx.send(f"⚠️ Cog `{ext}` ist nicht geladen.")
        except Exception as e:
            await ctx.send(f"❌ Fehler:\n```py\n{e}```")

    @ext_group.command(name="reload")
    @commands.is_owner()
    async def ext_reload(self, ctx: commands.Context, name: str):
        ext = resolve_extension(name)

        # Erst antworten, dann reloaden (wichtig!)
        await ctx.send(f"🔁 Lade Cog `{ext}` neu...")

        async def do_reload():
            await asyncio.sleep(0.2)  # gibt Discord Zeit, die Message zu senden
            try:
                await self.bot.reload_extension(ext)
                print(f"[DEV] Cog neu geladen: {ext}")
            except commands.ExtensionNotLoaded:
                print(f"[DEV] Cog nicht geladen: {ext}")
            except Exception as e:
                print(f"[DEV][RELOAD ERROR] {ext}: {e}")

        asyncio.create_task(do_reload())

    @ext_group.command(name="list")
    @commands.is_owner()
    async def ext_list(self, ctx: commands.Context):
        if not self.bot.extensions:
            await ctx.send("Keine Cogs geladen.")
            return

        await ctx.send(
            "**📦 Geladene Cogs:**\n" +
            "\n".join(f"• `{ext}`" for ext in self.bot.extensions)
        )

    # --- Sourcecode anzeigen (passt für persistente View) ---
    @commands.command(name="source")
    @commands.is_owner()
    async def source(self, ctx, *, command_name: str = None):
        """Zeigt den Quellcode eines Slash-Commands (auch Subcommands wie /levelsystem rank) oder des gesamten Cogs."""
        if command_name is None:
            try:
                source = inspect.getsource(self.__class__)
                code_chunks = chunk_code_lines(source)
                if len(code_chunks) == 1:
                    await ctx.send(f"```python\n{code_chunks[0]}```")
                else:
                    view = CodeScroller(code_chunks)
                    await ctx.send(f"```python\n{code_chunks[0]}```\nSeite 1/{len(code_chunks)}", view=view)
            except Exception as e:
                await ctx.send(f"Fehler: {e}")
            return

        cmd = find_app_command(self.bot, command_name)
        if not cmd:
            await ctx.send(f"Slash Command `{command_name}` nicht gefunden.")
            return

        try:
            source = inspect.getsource(cmd.callback)
            code_chunks = chunk_code_lines(source)
            if len(code_chunks) == 1:
                await ctx.send(f"```python\n{code_chunks[0]}```")
            else:
                view = CodeScroller(code_chunks)
                await ctx.send(f"```python\n{code_chunks[0]}```\nSeite 1/{len(code_chunks)}", view=view)
        except Exception as e:
            await ctx.send(f"Fehler beim Abrufen des Quellcodes: {e}")

    # --- Memory ---
    @commands.command(name="memory")
    @commands.is_owner()
    async def memory(self, ctx):
        """Zeigt Speicherverbrauch des Bots."""
        self.commands_run += 1
        try:
            process = psutil.Process()
            mem = process.memory_info().rss / (1024 ** 2)  # MB
            await ctx.send(f"Speicherverbrauch: {mem:.2f} MB")
        except Exception as e:
            await ctx.send(f"Fehler: {e}")

    # --- Stats ---
    @commands.command(name="stats")
    @commands.is_owner()
    async def stats(self, ctx):
        """Zeigt ein paar Bot-Statistiken."""
        self.commands_run += 1
        uptime = time.time() - self.start_time
        embed = discord.Embed(title="Bot Statistiken", color=discord.Color.blurple())
        embed.add_field(name="Uptime", value=f"{uptime/60:.2f} Minuten")
        embed.add_field(name="Server (Guilds)", value=str(len(self.bot.guilds)))
        embed.add_field(name="Benutzer", value=str(len(self.bot.users)))
        embed.add_field(name="Commands ausgeführt", value=str(self.commands_run))
        embed.set_footer(text=f"Deine ID: {ctx.author.id}")
        await ctx.send(embed=embed)

    # --- Restart ---
    @commands.command(name="restart")
    @commands.is_owner()
    async def restart(self, ctx):
        """Startet den Bot-Service neu via systemctl."""
        await ctx.send("🔁 Astra wird neugestartet...")
        subprocess.Popen(["/usr/bin/systemctl", "restart", "astrabot.service"])
        await self.bot.close()

    # --- Logs ---
    @commands.command(name="logs")
    @commands.is_owner()
    async def logs(self, ctx, live: bool = False):
        """
        Zeigt Logs an.
        live=True -> live stream mit Nachricht bearbeiten.
        live=False -> einmaligen Output senden.
        """
        if not live:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/journalctl", "-u", "astrabot.service", "-n", "50",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode() + stderr.decode()
            if len(output) > 1900:
                output = output[-1900:]
            await ctx.send(f"```bash\n{output}```")
        else:
            message = await ctx.send("Starte Live-Log-Stream...")

            process = await asyncio.create_subprocess_exec(
                "/usr/bin/journalctl", "-u", "astrabot.service", "-f", "-n", "10",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            logs = ""
            try:
                async for line in process.stdout:
                    line_decoded = line.decode("utf-8").rstrip()
                    logs += line_decoded + "\n"

                    if len(logs) > 1800:
                        logs = "\n".join(logs.split("\n")[-10:])
                    await message.edit(content=f"```bash\n{logs}```")
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    # --- Update ---
    @commands.command(name="update")
    @commands.is_owner()
    async def update(self, ctx):
        """Führt git pull im /root/Astra Verzeichnis aus."""
        await ctx.send("Ziehe Updates vom Git-Repo in /root/Astra...")

        proc = subprocess.run(
            ["/usr/bin/git", "-C", "/root/Astra", "pull"],
            capture_output=True,
            text=True,
            timeout=30
        )

        output = proc.stdout + proc.stderr
        if len(output) > 1900:
            output = output[:1900] + "\n... (gekürzt)"

        await ctx.send(f"```bash\n{output}```")

        await run_sql_file(self.bot.pool, SCHEMA_PATH)

    # --- Sysinfo ---
    @commands.command(name="sysinfo")
    @commands.is_owner()
    async def sysinfo(self, ctx):
        """Zeigt CPU- und RAM-Auslastung des Servers."""
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        await ctx.send(
            f"**System Info:**\n"
            f"CPU-Auslastung: {cpu}%\n"
            f"RAM-Auslastung: {mem.percent}% ({mem.used // 1024 ** 2}MB / {mem.total // 1024 ** 2}MB)"
        )


async def setup(bot: commands.Bot) -> None:

    # Persistente Views
    bot.add_view(CodeScroller(code_chunks=["Dummy"]))

    await bot.add_cog(CommandTracking(bot))
    await bot.add_cog(DevTools(bot))
