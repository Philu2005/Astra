import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import math
from datetime import datetime, timezone

ASTRA_BLUE = discord.Colour.from_rgb(88, 101, 242)

import re

# =========================================================
# TIME CONVERT
# =========================================================

def convert(time: str):
    if not time:
        return -1

    time = time.lower().replace(",", " ").strip()

    units = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800
    }

    # Unterstützt:
    # 1h 30m | 1h30m | 1.5h | 30m | 10
    pattern = r'(\d+(?:\.\d+)?)([a-z]*)'

    matches = re.findall(pattern, time)

    if not matches:
        return -1

    total = 0
    found_valid = False

    for value, unit in matches:
        if value == "":
            continue

        try:
            value = float(value)
        except:
            return -1

        # keine Einheit → Sekunden
        if unit == "":
            total += value
            found_valid = True
            continue

        if unit not in units:
            return -1

        total += value * units[unit]
        found_valid = True

    if not found_valid:
        return -1

    return int(total)


# =========================================================
# MODAL (FIXED)
# =========================================================

class ReminderCreateModal(ui.Modal, title="Neue Erinnerung"):

    beschreibung = ui.TextInput(
        label="🧠 Beschreibung",
        style=discord.TextStyle.paragraph,
        placeholder="Was soll ich dir merken?",
        max_length=500
    )

    zeit = ui.TextInput(
        label="⏳ Zeit",
        placeholder="z.B. 10m / 1h30m / 1.5h / 1h, 30m",
        max_length=20
    )

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        seconds = convert(self.zeit.value)

        if seconds <= 0:
            return await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Ungültige Zeitangabe",
                ephemeral=True
            )

        timestamp = int(discord.utils.utcnow().timestamp() + seconds)
        when = datetime.fromtimestamp(timestamp, tz=timezone.utc)

        async with self.view.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminder(userID, grund, time) VALUES(%s, %s, %s)",
                    (interaction.user.id, self.beschreibung.value, timestamp)
                )
                reminder_id = cur.lastrowid

        task = asyncio.create_task(
            self.view.cog.reminder_task(reminder_id, interaction.user.id, self.beschreibung.value, when)
        )

        self.view.cog.tasks[reminder_id] = task

        await self.view.reload(interaction)


class ReminderManagerView(ui.LayoutView):

    def __init__(self, bot, cog, user):
        super().__init__(timeout=180)
        self.bot = bot
        self.cog = cog
        self.user = user

        self.page = 0
        self.reminders = []

        self.state = "overview"
        self.delete_target = None
        self.delete_data = None

    async def load(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, grund, time FROM reminder WHERE userID=%s ORDER BY time ASC",
                    (self.user.id,)
                )
                self.reminders = await cur.fetchall()

    async def reload(self, interaction):
        await self.load()

        # 🔥 AUTO FIX: Wenn keine Reminder → zurück zu Overview
        if not self.reminders and self.state == "list":
            self.state = "overview"
            self.page = 0

        self.build()

        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)

    def build(self):
        self.clear_items()
        container = ui.Container(accent_color=ASTRA_BLUE.value)

        per_page = 3

        # ================= HEADER =================
        help_btn = ui.Button(
            emoji="<:Astra_support:1141303923752325210>",
            style=discord.ButtonStyle.secondary
        )

        async def help_cb(interaction):
            self.state = "help"
            await self.reload(interaction)

        help_btn.callback = help_cb

        # ================= HEADER =================
        # ================= HEADER =================
        if self.state != "help":
            help_btn = ui.Button(
                emoji="<:Astra_support:1141303923752325210>",
                style=discord.ButtonStyle.secondary
            )

            async def help_cb(interaction):
                self.state = "help"
                await self.reload(interaction)

            help_btn.callback = help_cb

            container.add_item(ui.Section(
                ui.TextDisplay(
                    "# <:Astra_time:1141303932061233202> Reminder Manager\n"
                    f"╰➤ **{len(self.reminders)} Erinnerungen gespeichert**"
                ),
                accessory=help_btn
            ))
        else:
            container.add_item(ui.TextDisplay(
                "# <:Astra_support:1141303923752325210> Hilfe & Guide\n"
                f"╰➤ **{len(self.reminders)} Erinnerungen gespeichert**"
            ))

        container.add_item(ui.Separator())

        # ================= HELP =================
        if self.state == "help":

            container.add_item(ui.TextDisplay(
                "\n"
                "## Erinnerungen\n"
                "Behalte alle deine Erinnerungen im Blick – einfach, schnell und übersichtlich.\n"
            ))

            container.add_item(ui.Separator())

            container.add_item(ui.TextDisplay(
                "### <:Astra_info:1141303860556738620> Übersicht\n"
                "<:Astra_punkt:1141303896745201696> Verwalte alle deine Erinnerungen zentral an einem Ort\n"
                "<:Astra_punkt:1141303896745201696> Erstelle neue Einträge und behalte bestehende jederzeit im Blick\n"
                "<:Astra_punkt:1141303896745201696> Entferne Erinnerungen unkompliziert, sobald du sie nicht mehr brauchst\n"
            ))

            container.add_item(ui.Separator())

            container.add_item(ui.TextDisplay(
                "### <:Astra_settings:1141303908778639490> Funktionen\n"
                "<:Astra_punkt:1141303896745201696> Erstelle individuelle Erinnerungen mit eigener Zeitangabe\n"
                "<:Astra_punkt:1141303896745201696> Nutze Quick-Reminder für sofortige Erinnerungen (10 Minuten, 1 Stunde oder 1 Tag)\n"
                "<:Astra_punkt:1141303896745201696> Lösche Erinnerungen direkt über <:Astra_x:1141303954555289600> ohne Umwege\n"
                "<:Astra_punkt:1141303896745201696> Navigiere einfach zwischen mehreren Seiten und Einträgen\n"
            ))

            container.add_item(ui.Separator())

            container.add_item(ui.TextDisplay(
                "### <:Astra_light_on:1141303864134467675> Tipps\n"
                "<:Astra_punkt:1141303896745201696> Quick-Buttons eignen sich perfekt für häufige oder spontane Erinnerungen\n"
                "<:Astra_punkt:1141303896745201696> Die angezeigten Zeiten werden automatisch angepasst und aktuell gehalten\n"
            ))

            home_btn = ui.Button(
                label="Home",
                style=discord.ButtonStyle.secondary,
                emoji="<:Astra_arrow_backwards:1392540551546671348>"
            )

            async def home_cb(interaction):
                self.state = "overview"
                await self.reload(interaction)

            home_btn.callback = home_cb

            container.add_item(ui.ActionRow(home_btn))

        # ================= OVERVIEW =================
        elif self.state == "overview":

            if not self.reminders:
                container.add_item(ui.TextDisplay(
                    "## <:Astra_x:1141303954555289600> Keine Reminder vorhanden\n\n"
                    "\u200b\n"
                    "<:Astra_light_on:1141303864134467675> Starte mit deinem ersten Reminder!"
                ))

                create_btn = ui.Button(
                    label="Erstellen",
                    style=discord.ButtonStyle.success,
                    emoji="<:Astra_accept:1141303821176422460>"
                )

                async def create_cb(interaction):
                    await interaction.response.send_modal(ReminderCreateModal(self))

                create_btn.callback = create_cb

                quick_10m = ui.Button(label="10m", style=discord.ButtonStyle.secondary, emoji="⏱️")
                quick_1h = ui.Button(label="1h", style=discord.ButtonStyle.secondary, emoji="⏱️")
                quick_1d = ui.Button(label="1d", style=discord.ButtonStyle.secondary, emoji="⏱️")

                async def quick_create(interaction, seconds):
                    ts = int(discord.utils.utcnow().timestamp() + seconds)

                    async with self.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "INSERT INTO reminder(userID, grund, time) VALUES(%s, %s, %s)",
                                (interaction.user.id, "Quick Reminder", ts)
                            )
                            rid = cur.lastrowid

                    self.cog.tasks[rid] = asyncio.create_task(
                        self.cog.reminder_task(
                            rid, interaction.user.id, "Quick Reminder",
                            datetime.fromtimestamp(ts, timezone.utc)
                        )
                    )

                    await self.reload(interaction)

                quick_10m.callback = lambda i: quick_create(i, 600)
                quick_1h.callback = lambda i: quick_create(i, 3600)
                quick_1d.callback = lambda i: quick_create(i, 86400)

                container.add_item(ui.ActionRow(create_btn))
                container.add_item(ui.ActionRow(quick_10m, quick_1h, quick_1d))

            else:
                container.add_item(ui.TextDisplay(
                    "## Übersicht\n\n"
                    "<:Astra_time:1141303932061233202> "
                    "Klicke auf den folgenden Button um alle Reminder anzuzeigen"
                ))

                show_btn = ui.Button(
                    label="Reminder anzeigen",
                    style=discord.ButtonStyle.primary
                )

                async def show_cb(interaction):
                    self.state = "list"
                    await self.reload(interaction)

                show_btn.callback = show_cb

                create_btn = ui.Button(
                    label="Erstellen",
                    style=discord.ButtonStyle.success,
                    emoji="<:Astra_accept:1141303821176422460>"
                )

                async def create_cb(interaction):
                    await interaction.response.send_modal(ReminderCreateModal(self))

                create_btn.callback = create_cb

                container.add_item(ui.ActionRow(show_btn))
                container.add_item(ui.ActionRow(create_btn))

        # ================= LIST =================
        elif self.state == "list":

            if not self.reminders:
                container.add_item(ui.TextDisplay(
                    "<:Astra_x:1141303954555289600> Keine Erinnerungen vorhanden"
                ))
            else:
                start = self.page * per_page
                current = self.reminders[start:start + per_page]

                for index, (rid, grund, ts) in enumerate(current, start=start + 1):

                    delete_btn = ui.Button(
                        emoji="<:Astra_x:1141303954555289600>",
                        style=discord.ButtonStyle.danger
                    )

                    async def delete_cb(interaction, rid=rid, grund=grund, ts=ts):
                        self.state = "confirm"
                        self.delete_target = rid
                        self.delete_data = (grund, ts)
                        await self.reload(interaction)

                    delete_btn.callback = delete_cb

                    section = ui.Section(
                        ui.TextDisplay(
                            f"## <:Astra_punkt:1141303896745201696> Erinnerung {index}\n"
                            f"> {grund}\n\n"
                            f"<:Astra_time:1141303932061233202> <t:{ts}:R>\n"
                            f"<:Astra_calender:1141303828625489940> <t:{ts}:F>"
                        ),
                        accessory=delete_btn
                    )

                    container.add_item(section)
                    container.add_item(ui.Separator())

            prev_btn = ui.Button(emoji="<:Astra_arrow_backwards:1392540551546671348>", style=discord.ButtonStyle.secondary)
            home_btn = ui.Button(
                label="Home",
                style=discord.ButtonStyle.secondary
            )
            next_btn = ui.Button(emoji="<:Astra_arrow:1141303823600717885>", style=discord.ButtonStyle.secondary)

            prev_btn.disabled = self.page == 0
            next_btn.disabled = (self.page + 1) * per_page >= len(self.reminders)

            async def prev_cb(i):
                self.page -= 1
                await self.reload(i)

            async def next_cb(i):
                self.page += 1
                await self.reload(i)

            async def home_cb(i):
                self.state = "overview"
                await self.reload(i)

            prev_btn.callback = prev_cb
            next_btn.callback = next_cb
            home_btn.callback = home_cb

            create_btn = ui.Button(
                label="Erstellen",
                style=discord.ButtonStyle.success,
                emoji="<:Astra_accept:1141303821176422460>"
            )

            async def create_cb(i):
                await i.response.send_modal(ReminderCreateModal(self))

            create_btn.callback = create_cb

            quick_10m = ui.Button(label="10m", style=discord.ButtonStyle.secondary, emoji="⏱️")
            quick_1h = ui.Button(label="1h", style=discord.ButtonStyle.secondary, emoji="⏱️")
            quick_1d = ui.Button(label="1d", style=discord.ButtonStyle.secondary, emoji="⏱️")

            async def quick_create(i, sec):
                ts = int(discord.utils.utcnow().timestamp() + sec)

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO reminder(userID, grund, time) VALUES(%s,%s,%s)",
                            (i.user.id, "Quick Reminder", ts)
                        )
                        rid = cur.lastrowid

                self.cog.tasks[rid] = asyncio.create_task(
                    self.cog.reminder_task(
                        rid, i.user.id, "Quick Reminder",
                        datetime.fromtimestamp(ts, timezone.utc)
                    )
                )

                await self.reload(i)

            quick_10m.callback = lambda i: quick_create(i, 600)
            quick_1h.callback = lambda i: quick_create(i, 3600)
            quick_1d.callback = lambda i: quick_create(i, 86400)

            container.add_item(ui.ActionRow(prev_btn, home_btn, next_btn))
            container.add_item(ui.Separator())
            container.add_item(ui.ActionRow(create_btn))
            container.add_item(ui.ActionRow(quick_10m, quick_1h, quick_1d))

        # ================= CONFIRM =================
        elif self.state == "confirm":

            grund, _ = self.delete_data

            container.add_item(ui.TextDisplay(
                f"## <:Astra_x:1141303954555289600> Wirklich löschen?\n"
                f"> {grund[:80]}{'...' if len(grund) > 80 else ''}"
            ))

            yes_btn = ui.Button(
                label="Ja",
                style=discord.ButtonStyle.danger,
                emoji="<:Astra_accept:1141303821176422460>"
            )

            no_btn = ui.Button(
                label="Nein",
                style=discord.ButtonStyle.secondary,
                emoji="<:Astra_x:1141303954555289600>"
            )

            async def yes_cb(i):
                rid = self.delete_target

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "DELETE FROM reminder WHERE id=%s AND userID=%s",
                            (rid, self.user.id)
                        )

                self.state = "list"
                await self.reload(i)

            async def no_cb(i):
                self.state = "list"
                await self.reload(i)

            yes_btn.callback = yes_cb
            no_btn.callback = no_cb

            container.add_item(ui.ActionRow(yes_btn, no_btn))

        self.add_item(container)

# =========================================================
# COG
# =========================================================

@app_commands.guild_only()
class Reminder(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.tasks = {}
        self.loader_task = None

    async def cog_load(self):
        self.loader_task = asyncio.create_task(self.load_reminders())

    async def cog_unload(self):

        if self.loader_task:
            self.loader_task.cancel()

        for task in self.tasks.values():
            task.cancel()

        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

        self.tasks.clear()

    async def load_reminders(self):
        await self.bot.wait_until_ready()

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, userID, grund, time FROM reminder WHERE time > UNIX_TIMESTAMP()"
                )
                rows = await cur.fetchall()

        for rid, uid, grund, ts in rows:
            when = datetime.fromtimestamp(int(ts), timezone.utc)

            if rid in self.tasks:
                continue  # verhindert doppelte Tasks

            task = asyncio.create_task(
                self.reminder_task(rid, uid, grund, when)
            )

            self.tasks[rid] = task

    async def reminder_task(self, rid, uid, grund, when):
        await self.bot.wait_until_ready()

        try:
            await discord.utils.sleep_until(when)
        except asyncio.CancelledError:
            return  # <- EXTREM WICHTIG

        try:
            user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
        except Exception as e:
            print(e)
            return

        embed = discord.Embed(
            title="<:Astra_time:1141303932061233202> Erinnerung",
            description=f"> {grund}",
            color=ASTRA_BLUE
        )

        embed.add_field(name="⏳ Fällig", value=f"<t:{int(when.timestamp())}:R>", inline=True)
        embed.add_field(name="📅 Datum", value=f"<t:{int(when.timestamp())}:F>", inline=True)

        embed.set_footer(text="Astra Reminder System")

        try:
            await user.send(embed=embed)
        except Exception as e:
            print(e)

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM reminder WHERE id=%s", (rid,))

        self.tasks.pop(rid, None)

    @app_commands.command(name="erinnerungen", description="Öffnet eine Übersicht deiner Erinnerungen mit Optionen zum Erstellen, Löschen und Verwalten")
    async def manager(self, interaction: discord.Interaction):

        view = ReminderManagerView(self.bot, self, interaction.user)
        await view.load()
        view.build()

        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Reminder(bot))
