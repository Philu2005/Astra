import discord
from discord.ext import commands
import textwrap
import traceback
from math import ceil
import psutil
from collections import defaultdict
import inspect
import asyncio
import subprocess
import time
from typing import List, Optional
import logging
from pathlib import Path
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from utils.db_scheme import run_sql_file


class AstraEmojis:
    TIME = "<:Astra_time:1141303932061233202>"
    CALENDAR = "<:Astra_calender:1141303828625489940>"
    USER = "<:Astra_user:1141303940365959241>"
    GUILD = "<:Astra_file2:1141303839543279666>"
    SEARCH = "<:Astra_support:1141303923752325210>"
    FILTER = "<:Astra_pin:1141303893616250900>"
    TIMER = "<:Astra_time:1141303932061233202>"
    SETTINGS = "<:Astra_settings:1141303908778639490>"
    RESET = "<:Astra_x:1141303954555289600>"
    FILE = "<:Astra_url:1141303937056657458>"
    CLOSE = "<:Astra_x:1141303954555289600>"
    PREV = "<:Astra_arrow_backwards:1392540551546671348>"
    NEXT = "<:Astra_arrow:1141303823600717885>"
    SUCCESS = "<:Astra_accept:1141303821176422460>"
    INFO = "<:Astra_info:1141303860556738620>"


def resolve_extension(name: str) -> str:
    """
    dev        -> cogs.dev
    cogs.dev   -> cogs.dev
    """
    if "." in name:
        return name
    return f"cogs.{name}"


@dataclass
class CmdLogFilters:
    preset: str = "today"
    custom_days: Optional[int] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    guild_id: Optional[int] = None
    user_id: Optional[int] = None
    command_query: Optional[str] = None
    sort_by: str = "newest"
    options: set[str] = field(default_factory=lambda: {"with_subcommands"})


class CommandLogView(discord.ui.View):
    def __init__(self, ctx, rows, pages, title: str):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.rows = rows
        self.pages = pages
        self.page = 0
        self.title = title

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

        embed = discord.Embed(title=self.title, color=discord.Color.blurple())

        for guild_id, user_id, cmd, sub, used_at in chunk:
            guild = self.ctx.bot.get_guild(guild_id)
            user = self.ctx.bot.get_user(user_id)

            cmd_name = f"/{cmd}" + (f" {sub}" if sub else "")
            time_str = used_at.strftime("%d.%m.%Y %H:%M:%S")

            # Ein übersichtlicheres Feld mit Markdowns und Emojis
            embed.add_field(
                name=f"{AstraEmojis.TIME} {time_str}",
                value=(
                    f"**Command:** `{cmd_name}`\n"
                    f"**User:** {user.mention if user else f'`{user_id}`'} (`{user_id}`)\n"
                    f"**Server:** {f'**{guild.name}**' if guild else f'`{guild_id}`'}"
                ),
                inline=False
            )

        embed.set_footer(text=f"Seite {self.page + 1}/{self.pages} • {len(self.rows)} Gesamtergebnisse")
        return embed

    @discord.ui.button(emoji=AstraEmojis.PREV, style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(
                embed=self.make_embed(), view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji=AstraEmojis.NEXT, style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _):
        if self.page < self.pages - 1:
            self.page += 1
            await interaction.response.edit_message(
                embed=self.make_embed(), view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji=AstraEmojis.CLOSE, style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _):
        await interaction.message.delete()
        self.stop()

class CmdLogOverviewView(discord.ui.View):
    def __init__(self, ctx, rows, title: str):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.rows = rows
        self.pages = ceil(len(rows) / PAGE_SIZE)
        self.title = title

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
        view = CommandLogView(self.ctx, self.rows, self.pages, self.title)
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

    @discord.ui.button(emoji=AstraEmojis.PREV, style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _):
        if self.index > 0:
            self.index -= 1
            await interaction.response.edit_message(
                embed=self.pages[self.index], view=self
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji=AstraEmojis.NEXT, style=discord.ButtonStyle.secondary)
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


def parse_cmdlog_datetime(value: str) -> Optional[datetime]:
    raw = (value or "").strip()
    if not raw:
        return None

    formats = (
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    )

    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
                parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return parsed
        except ValueError:
            continue

    return None


def build_cmdlog_query(filters: CmdLogFilters, default_guild_id: Optional[int] = None):
    clauses = []
    params = []
    now = datetime.utcnow()

    if filters.preset == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        clauses.append("used_at >= %s")
        params.append(start)
    elif filters.preset == "last7":
        clauses.append("used_at >= %s")
        params.append(now - timedelta(days=7))
    elif filters.preset == "last30":
        clauses.append("used_at >= %s")
        params.append(now - timedelta(days=30))
    elif filters.preset == "custom_days" and filters.custom_days:
        clauses.append("used_at >= %s")
        params.append(now - timedelta(days=filters.custom_days))
    elif filters.preset == "custom_range":
        if filters.start_at:
            clauses.append("used_at >= %s")
            params.append(filters.start_at)
        if filters.end_at:
            clauses.append("used_at <= %s")
            params.append(filters.end_at)

    guild_id = filters.guild_id
    if guild_id is None and "only_current_guild" in filters.options:
        guild_id = default_guild_id

    if guild_id:
        clauses.append("guild_id = %s")
        params.append(guild_id)

    if filters.user_id:
        clauses.append("user_id = %s")
        params.append(filters.user_id)

    command_query = (filters.command_query or "").strip()
    if command_query:
        exact = "exact_command" in filters.options
        include_subcommands = "with_subcommands" in filters.options

        if exact:
            if " " in command_query and include_subcommands:
                base, _, sub = command_query.partition(" ")
                clauses.append("command = %s")
                params.append(base.strip().lower())
                clauses.append("subcommand = %s")
                params.append(sub.strip().lower())
            elif include_subcommands:
                clauses.append("(command = %s OR subcommand = %s)")
                params.extend([command_query.lower(), command_query.lower()])
            else:
                clauses.append("command = %s")
                params.append(command_query.lower())
        else:
            like_value = f"%{command_query.lower()}%"
            if include_subcommands:
                clauses.append("(LOWER(command) LIKE %s OR LOWER(COALESCE(subcommand, '')) LIKE %s)")
                params.extend([like_value, like_value])
            else:
                clauses.append("LOWER(command) LIKE %s")
                params.append(like_value)

    where_sql = " AND ".join(clauses) if clauses else "1=1"

    order_map = {
        "newest": "used_at DESC",
        "oldest": "used_at ASC",
        "command": "command ASC, subcommand ASC, used_at DESC",
        "guild": "guild_id ASC, used_at DESC",
        "user": "user_id ASC, used_at DESC",
    }
    order_sql = order_map.get(filters.sort_by, order_map["newest"])

    query = f"""
        SELECT guild_id, user_id, command, subcommand, used_at
        FROM command_usage
        WHERE {where_sql}
        ORDER BY {order_sql}
    """
    return query, params


def build_cmdlog_title(filters: CmdLogFilters) -> str:
    if filters.preset == "today":
        return "📊 CmdLog • Heute"
    if filters.preset == "last7":
        return "📊 CmdLog • Letzte 7 Tage"
    if filters.preset == "last30":
        return "📊 CmdLog • Letzte 30 Tage"
    if filters.preset == "custom_days" and filters.custom_days:
        return f"📊 CmdLog • Letzte {filters.custom_days} Tage"
    if filters.preset == "custom_range":
        return "📊 CmdLog • Eigener Zeitraum"
    return "📊 CmdLog • Gesamtes Log"


def build_cmdlog_filter_summary(filters: CmdLogFilters, ctx: commands.Context) -> str:
    lines = []

    preset_map = {
        "today": "Heute",
        "last7": "Letzte 7 Tage",
        "last30": "Letzte 30 Tage",
        "custom_days": f"Letzte {filters.custom_days or '?'} Tage",
        "custom_range": "Eigener Zeitraum",
        "all": "Gesamtes Log",
    }
    lines.append(f"**Zeitraum:** {preset_map.get(filters.preset, 'Unbekannt')}")

    if filters.start_at or filters.end_at:
        start = filters.start_at.strftime("%d.%m.%Y %H:%M") if filters.start_at else "offen"
        end = filters.end_at.strftime("%d.%m.%Y %H:%M") if filters.end_at else "jetzt"
        lines.append(f"**Fenster:** `{start}` → `{end}`")

    if filters.guild_id:
        guild = ctx.bot.get_guild(filters.guild_id)
        label = guild.name if guild else filters.guild_id
        lines.append(f"**Server:** `{filters.guild_id}` ({label})")
    elif "only_current_guild" in filters.options and ctx.guild:
        lines.append(f"**Server:** Nur aktueller Server (`{ctx.guild.id}`)")
    else:
        lines.append("**Server:** Alle")

    lines.append(f"**User:** `{filters.user_id}`" if filters.user_id else "**User:** Alle")
    lines.append(f"**Command:** `{filters.command_query}`" if filters.command_query else "**Command:** Alle")

    option_labels = []
    if "with_subcommands" in filters.options:
        option_labels.append("Subcommands einbeziehen")
    if "exact_command" in filters.options:
        option_labels.append("Exact Match")
    if "compact_preview" in filters.options:
        option_labels.append("Kompakte Vorschau")
    if "only_current_guild" in filters.options and ctx.guild:
        option_labels.append("Nur aktueller Server")
    lines.append(f"**Optionen:** {', '.join(option_labels) if option_labels else 'Keine'}")

    sort_map = {
        "newest": "Neueste zuerst",
        "oldest": "Älteste zuerst",
        "command": "Nach Command",
        "guild": "Nach Server",
        "user": "Nach User",
    }
    lines.append(f"**Sortierung:** {sort_map.get(filters.sort_by, 'Neueste zuerst')}")
    return "\n".join(lines)


def build_cmdlog_result_summary(ctx: commands.Context, rows: list, filters: CmdLogFilters) -> str:
    if not rows:
        return (
            "## Ergebnis\n"
            "Keine Einträge für die aktuellen Filter gefunden.\n\n"
            "Passe Zeitraum, IDs oder Command-Filter an und starte die Suche erneut."
        )

    total = len(rows)
    commands_count = defaultdict(int)
    users_count = defaultdict(int)
    guilds_count = defaultdict(int)

    for guild_id, user_id, cmd, sub, _used_at in rows:
        commands_count[f"/{cmd}" + (f" {sub}" if sub else "")] += 1
        users_count[user_id] += 1
        guilds_count[guild_id] += 1

    top_commands = sorted(commands_count.items(), key=lambda item: item[1], reverse=True)[:3]
    top_users = sorted(users_count.items(), key=lambda item: item[1], reverse=True)[:3]
    top_guilds = sorted(guilds_count.items(), key=lambda item: item[1], reverse=True)[:3]

    preview_count = 3 if "compact_preview" in filters.options else 5
    preview_rows = rows[:preview_count]
    preview = []
    for guild_id, user_id, cmd, sub, used_at in preview_rows:
        guild = ctx.bot.get_guild(guild_id)
        guild_label = f"**{guild.name}**" if guild else f"`{guild_id}`"
        cmd_label = f"`/{cmd}" + (f" {sub}`" if sub else "`")
        time_str = used_at.strftime("%H:%M:%S")
        date_str = used_at.strftime("%d.%m.%Y")
        
        preview.append(
            f"{AstraEmojis.CALENDAR} `{date_str}` {AstraEmojis.TIME} `{time_str}`\n"
            f"└ {cmd_label} • {AstraEmojis.USER} <@{user_id}> • {AstraEmojis.GUILD} {guild_label}"
        )

    return (
        "## 🔍 Letzte Ergebnisse\n"
        f"**Treffer:** `{total}`\n"
        f"**Commands:** `{len(commands_count)}` • **User:** `{len(users_count)}` • **Server:** `{len(guilds_count)}`\n\n"
        f"**Top 3 Commands:** {', '.join(f'`{name}` ({count})' for name, count in top_commands) or '—'}\n"
        f"**Top 3 User:** {', '.join(f'<@{uid}> ({count})' for uid, count in top_users) or '—'}\n"
        f"**Top 3 Server:** {', '.join(f'**{ctx.bot.get_guild(gid).name if ctx.bot.get_guild(gid) else gid}** ({count})' for gid, count in top_guilds) or '—'}\n\n"
        "**Vorschau:**\n"
        + ("\n\n".join(preview) if preview else "—")
    )


class CmdLogFiltersModal(discord.ui.Modal, title="CmdLog Filter"):
    guild_id = discord.ui.TextInput(
        label="Server ID",
        required=False,
        placeholder="leer = alle Server"
    )
    user_id = discord.ui.TextInput(
        label="User ID",
        required=False,
        placeholder="leer = alle User"
    )
    command_name = discord.ui.TextInput(
        label="Command / Suchbegriff",
        required=False,
        placeholder="z.B. levelsystem oder levelsystem rank"
    )

    def __init__(self, view: "CmdLogDashboardView"):
        super().__init__()
        self.view = view
        self.guild_id.default = str(view.filters.guild_id or "")
        self.user_id.default = str(view.filters.user_id or "")
        self.command_name.default = view.filters.command_query or ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild_raw = self.guild_id.value.strip()
            user_raw = self.user_id.value.strip()

            self.view.filters.guild_id = int(guild_raw) if guild_raw else None
            self.view.filters.user_id = int(user_raw) if user_raw else None
        except ValueError:
            await interaction.response.send_message(
                "Server ID und User ID müssen numerisch sein.",
                ephemeral=True
            )
            return

        self.view.filters.command_query = self.command_name.value.strip() or None
        self.view.status_message = "Filter aktualisiert. Starte jetzt die Suche."
        self.view._build()
        await interaction.response.edit_message(view=self.view)


class CmdLogTimeModal(discord.ui.Modal, title="CmdLog Zeitraum"):
    custom_days = discord.ui.TextInput(
        label="Eigene Tage",
        required=False,
        placeholder="z.B. 14"
    )
    start_at = discord.ui.TextInput(
        label="Start",
        required=False,
        placeholder="DD.MM.YYYY HH:MM oder YYYY-MM-DD"
    )
    end_at = discord.ui.TextInput(
        label="Ende",
        required=False,
        placeholder="DD.MM.YYYY HH:MM oder YYYY-MM-DD"
    )

    def __init__(self, view: "CmdLogDashboardView"):
        super().__init__()
        self.view = view
        self.custom_days.default = str(view.filters.custom_days or "")
        self.start_at.default = view.filters.start_at.strftime("%d.%m.%Y %H:%M") if view.filters.start_at else ""
        self.end_at.default = view.filters.end_at.strftime("%d.%m.%Y %H:%M") if view.filters.end_at else ""

    async def on_submit(self, interaction: discord.Interaction):
        days_raw = self.custom_days.value.strip()
        start_raw = self.start_at.value.strip()
        end_raw = self.end_at.value.strip()

        if days_raw:
            if not days_raw.isdigit() or int(days_raw) <= 0:
                await interaction.response.send_message(
                    "Die Tagesanzahl muss eine positive Zahl sein.",
                    ephemeral=True
                )
                return
            self.view.filters.preset = "custom_days"
            self.view.filters.custom_days = int(days_raw)
            self.view.filters.start_at = None
            self.view.filters.end_at = None
        elif start_raw or end_raw:
            start_at = parse_cmdlog_datetime(start_raw)
            end_at = parse_cmdlog_datetime(end_raw) if end_raw else datetime.utcnow()

            if start_raw and not start_at:
                await interaction.response.send_message(
                    "Start konnte nicht gelesen werden.",
                    ephemeral=True
                )
                return
            if end_raw and not end_at:
                await interaction.response.send_message(
                    "Ende konnte nicht gelesen werden.",
                    ephemeral=True
                )
                return
            if not start_at:
                await interaction.response.send_message(
                    "Für einen freien Zeitraum brauchst du mindestens einen Startwert.",
                    ephemeral=True
                )
                return
            if end_at and end_at < start_at:
                await interaction.response.send_message(
                    "Das Ende darf nicht vor dem Start liegen.",
                    ephemeral=True
                )
                return

            self.view.filters.preset = "custom_range"
            self.view.filters.custom_days = None
            self.view.filters.start_at = start_at
            self.view.filters.end_at = end_at
        else:
            self.view.filters.preset = "all"
            self.view.filters.custom_days = None
            self.view.filters.start_at = None
            self.view.filters.end_at = None

        self.view.status_message = "Zeitraum aktualisiert. Starte jetzt die Suche."
        self.view._build()
        await interaction.response.edit_message(view=self.view)


class CmdLogSettingsModal(discord.ui.Modal, title="CmdLog Einstellungen"):
    def __init__(self, view: "CmdLogDashboardView"):
        super().__init__()
        self.view = view

        # Da CheckboxGroup/RadioGroup in dieser discord.py-Version (2.7.0a) noch fehlen,
        # nutzen wir Select-Menüs (Dropdowns), die in Modals gut funktionieren.
        
        self.options_select = discord.ui.Select(
            placeholder="Wähle Anzeige-Optionen...",
            min_values=0,
            max_values=4,
            options=[
                discord.SelectOption(
                    label="Subcommands einbeziehen",
                    value="with_subcommands",
                    default="with_subcommands" in view.filters.options
                ),
                discord.SelectOption(
                    label="Command exakt matchen",
                    value="exact_command",
                    default="exact_command" in view.filters.options
                ),
                discord.SelectOption(
                    label="Kompakte Vorschau",
                    value="compact_preview",
                    default="compact_preview" in view.filters.options
                )
            ]
        )
        if view.ctx.guild is not None:
            self.options_select.add_option(
                label="Nur aktueller Server",
                value="only_current_guild",
                default="only_current_guild" in view.filters.options
            )
        self.add_item(self.options_select)

        self.sort_select = discord.ui.Select(
            placeholder="Sortierung wählen...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Neueste zuerst",
                    value="newest",
                    default=view.filters.sort_by == "newest"
                ),
                discord.SelectOption(
                    label="Älteste zuerst",
                    value="oldest",
                    default=view.filters.sort_by == "oldest"
                ),
                discord.SelectOption(
                    label="Nach Command",
                    value="command",
                    default=view.filters.sort_by == "command"
                ),
                discord.SelectOption(
                    label="Nach Server",
                    value="guild",
                    default=view.filters.sort_by == "guild"
                ),
                discord.SelectOption(
                    label="Nach User",
                    value="user",
                    default=view.filters.sort_by == "user"
                )
            ]
        )
        self.add_item(self.sort_select)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.filters.options = set(self.options_select.values)
        self.view.filters.sort_by = self.sort_select.values[0]
        
        self.view.status_message = "Einstellungen aktualisiert. Suche neu starten für Effekt."
        self.view._build()
        await interaction.response.edit_message(view=self.view)


class CmdLogDashboardView(discord.ui.LayoutView):
    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.filters = CmdLogFilters()
        self.rows: list = []
        self.title = build_cmdlog_title(self.filters)
        self.status_message = "Wähle Filter, dann starte die Suche."
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Nur der Bot-Owner darf das bedienen.", ephemeral=True)
            return False
        return True

    async def run_search(self):
        self.title = build_cmdlog_title(self.filters)
        query, params = build_cmdlog_query(self.filters, self.ctx.guild.id if self.ctx.guild else None)
        async with self.ctx.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                self.rows = await cur.fetchall()

    def _build(self):
        self.clear_items()

        # Hauptcontainer für das Dashboard
        container = discord.ui.Container(accent_color=discord.Color.blurple().value)
        
        # Header Section
        header_section = discord.ui.Section(
            discord.ui.TextDisplay(
                "# 📊 CmdLog Control Center\n"
                "Verwalte und durchsuche die Command-Logs effizient mit modernen Filtern."
            ),
            accessory=discord.ui.Thumbnail(self.ctx.bot.user.display_avatar.url)
        )
        container.add_item(header_section)
        container.add_item(discord.ui.Separator())

        # Suche & Status Section
        search_button = discord.ui.Button(
            label="Suche starten",
            emoji=AstraEmojis.SEARCH,
            style=discord.ButtonStyle.success
        )

        async def search_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            await self.run_search()
            self.status_message = f"{AstraEmojis.SUCCESS} Suche abgeschlossen. Treffer: **{len(self.rows)}**."
            self._build()
            await interaction.edit_original_response(view=self)

        search_button.callback = search_callback

        status_display = discord.ui.TextDisplay(
            f"### Status\n{self.status_message}"
        )
        container.add_item(discord.ui.Section(status_display, accessory=search_button))
        container.add_item(discord.ui.Separator())

        # Filter Übersicht
        filter_display = discord.ui.TextDisplay(
            "## 🧩 Aktive Filter\n"
            f"{build_cmdlog_filter_summary(self.filters, self.ctx)}"
        )
        container.add_item(filter_display)

        # Buttons für Modals
        filters_button = discord.ui.Button(label="IDs & Command", emoji=AstraEmojis.FILTER, style=discord.ButtonStyle.primary)
        async def filters_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(CmdLogFiltersModal(self))
        filters_button.callback = filters_callback

        time_button = discord.ui.Button(label="Zeitraum", emoji=AstraEmojis.TIMER, style=discord.ButtonStyle.primary)
        async def time_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(CmdLogTimeModal(self))
        time_button.callback = time_callback

        settings_button = discord.ui.Button(label="Einstellungen", emoji=AstraEmojis.SETTINGS, style=discord.ButtonStyle.primary)
        async def settings_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(CmdLogSettingsModal(self))
        settings_button.callback = settings_callback

        reset_button = discord.ui.Button(label="Reset", emoji=AstraEmojis.RESET, style=discord.ButtonStyle.danger)
        async def reset_callback(interaction: discord.Interaction):
            self.filters = CmdLogFilters()
            self.rows = []
            self.title = build_cmdlog_title(self.filters)
            self.status_message = "Alle Filter wurden zurückgesetzt."
            self._build()
            await interaction.response.edit_message(view=self)
        reset_button.callback = reset_callback

        full_log_button = discord.ui.Button(
            label="Vollständiges Log",
            emoji=AstraEmojis.FILE,
            style=discord.ButtonStyle.secondary,
            disabled=not self.rows
        )
        async def full_log_callback(interaction: discord.Interaction):
            view = CommandLogView(self.ctx, self.rows, ceil(len(self.rows) / PAGE_SIZE), self.title)
            await interaction.response.send_message(embed=view.make_embed(), view=view, ephemeral=True)
        full_log_button.callback = full_log_callback

        # ActionRows für die Buttons
        container.add_item(discord.ui.ActionRow(filters_button, time_button, settings_button, reset_button))
        
        # Preset Select bleibt für schnellen Zugriff
        container.add_item(discord.ui.ActionRow(CmdLogPresetQuickSelect(self)))
        
        container.add_item(discord.ui.Separator())

        # Ergebnis Zusammenfassung
        if self.rows:
            container.add_item(discord.ui.Section(
                discord.ui.TextDisplay(build_cmdlog_result_summary(self.ctx, self.rows, self.filters)),
                accessory=full_log_button
            ))
        else:
            container.add_item(discord.ui.TextDisplay("*Noch keine Ergebnisse geladen. Nutze die Filter und drücke auf Suche.*"))

        self.add_item(container)


class CmdLogPresetQuickSelect(discord.ui.Select):
    def __init__(self, view: "CmdLogDashboardView"):
        options = [
            discord.SelectOption(label="Heute", value="today", default=view.filters.preset == "today"),
            discord.SelectOption(label="Letzte 7 Tage", value="last7", default=view.filters.preset == "last7"),
            discord.SelectOption(label="Letzte 30 Tage", value="last30", default=view.filters.preset == "last30"),
            discord.SelectOption(label="Gesamtes Log", value="all", default=view.filters.preset == "all"),
        ]
        super().__init__(placeholder="Schnellwahl: Zeitraum", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: CmdLogDashboardView = self.view  # type: ignore
        view.filters.preset = self.values[0]
        if self.values[0] != "custom_days":
            view.filters.custom_days = None
        if self.values[0] != "custom_range":
            view.filters.start_at = None
            view.filters.end_at = None
        view.status_message = f"Zeitraum-Preset auf **{self.values[0]}** gesetzt."
        view._build()
        await interaction.response.edit_message(view=view)




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

    @discord.ui.button(emoji=AstraEmojis.PREV, style=discord.ButtonStyle.primary, custom_id="codescroller_prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current > 0:
            self.current -= 1
            await interaction.response.edit_message(
                content=f"```python\n{self.code_chunks[self.current]}```\nSeite {self.current+1}/{len(self.code_chunks)}",
                view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji=AstraEmojis.NEXT, style=discord.ButtonStyle.primary, custom_id="codescroller_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current < len(self.code_chunks) - 1:
            self.current += 1
            await interaction.response.edit_message(
                content=f"```python\n{self.code_chunks[self.current]}```\nSeite {self.current+1}/{len(self.code_chunks)}",
                view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji=AstraEmojis.CLOSE, style=discord.ButtonStyle.danger, row=0, custom_id="codescroller_delete")
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

    @discord.ui.button(emoji=AstraEmojis.PREV, style=discord.ButtonStyle.secondary)
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

    @discord.ui.button(emoji=AstraEmojis.NEXT, style=discord.ButtonStyle.secondary)
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
        view = CmdLogDashboardView(ctx)

        legacy = (period or "").strip().lower()
        if legacy in ("week", "woche", "7", "7d"):
            view.filters.preset = "last7"
            view.status_message = "Legacy-Parameter erkannt: letzte 7 Tage vorausgewählt."
        elif legacy in ("30", "30d", "month", "monat"):
            view.filters.preset = "last30"
            view.status_message = "Legacy-Parameter erkannt: letzte 30 Tage vorausgewählt."
        elif legacy.isdigit() and int(legacy) > 0:
            view.filters.preset = "custom_days"
            view.filters.custom_days = int(legacy)
            view.status_message = f"Legacy-Parameter erkannt: letzte {legacy} Tage vorausgewählt."
        elif legacy not in ("", "today", "heute"):
            view.status_message = "Interaktive CmdLog-Ansicht geöffnet. Den alten Parameter ersetzst du jetzt über die Filter im Panel."

        view.title = build_cmdlog_title(view.filters)
        view._build()
        await ctx.send(view=view)

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
    @commands.guild_only()
    @commands.command(name="serverlist", aliases=["servers"])
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

        proc = await asyncio.to_thread(
            subprocess.run,
            ["/usr/bin/git", "-C", "/root/Astra", "pull"],
            capture_output=True,
            text=True,
            timeout=30
        )

        output = proc.stdout + proc.stderr
        if len(output) > 1900:
            output = output[:1900] + "\n... (gekürzt)"

        await ctx.send(f"```bash\n{output}```")

        await run_sql_file(self.bot.pool)

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
