import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import math
from datetime import datetime, timezone

ASTRA_BLUE = discord.Colour.blue()


# =========================================================
#                     TIME CONVERT
# =========================================================

def convert(time):
    pos = ["s", "m", "h", "d", "w"]
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24, "w": 3600 * 24 * 7}
    unit = time[-1]

    if unit not in pos:
        return -1

    try:
        val = int(time[:-1])
    except:
        return -2

    return val * time_dict[unit]


# =========================================================
#                     MODAL
# =========================================================

class ReminderCreateModal(ui.Modal, title="Erinnerung erstellen"):

    beschreibung = ui.TextInput(
        label="Beschreibung",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    zeit = ui.TextInput(
        label="Zeit (z.B. 10m, 2h, 1d)",
        required=True,
        max_length=20
    )

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        seconds = convert(self.zeit.value)

        if seconds < 0:
            return await interaction.response.send_message("❌ Ungültige Zeit!", ephemeral=True)

        t1 = math.floor(discord.utils.utcnow().timestamp() + seconds)
        t2 = datetime.fromtimestamp(t1, tz=timezone.utc)

        async with self.view.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminder(userID, grund, time) VALUES(%s, %s, %s)",
                    (interaction.user.id, self.beschreibung.value, t1)
                )
                reminder_id = cur.lastrowid

        task = asyncio.create_task(
            self.view.cog.reminder_task(reminder_id, interaction.user.id, self.beschreibung.value, t2)
        )
        self.view.cog.tasks[reminder_id] = task

        await interaction.response.send_message(
            f"✅ Erinnerung erstellt (ID `{reminder_id}`)\n<t:{t1}:F>",
            ephemeral=True
        )


# =========================================================
#                     VIEW (MANAGER)
# =========================================================

class ReminderManagerView(ui.LayoutView):

    def __init__(self, bot, cog, user):
        super().__init__(timeout=180)
        self.bot = bot
        self.cog = cog
        self.user = user
        self.reminders = []

        self.page = 0
        self._build()

    async def load(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, grund, time FROM reminder WHERE userID=%s ORDER BY time ASC",
                    (self.user.id,)
                )
                self.reminders = await cur.fetchall()

    def _build(self):
        self.clear_items()

        container = ui.Container(accent_color=ASTRA_BLUE.value)

        # HEADER
        container.add_item(ui.TextDisplay(
            "# Erinnerungen Manager\n"
            "Verwalte alle deine Erinnerungen an einem Ort."
        ))

        container.add_item(ui.Separator())

        # LISTE
        if not self.reminders:
            container.add_item(ui.TextDisplay(
                "❌ Du hast keine aktiven Erinnerungen."
            ))
        else:
            start = self.page * 5
            end = start + 5

            for rid, grund, ts in self.reminders[start:end]:
                container.add_item(ui.TextDisplay(
                    f"**ID {rid}**\n"
                    f"{grund}\n"
                    f"⏱ <t:{ts}:F>"
                ))

        container.add_item(ui.Separator())

        # BUTTONS
        create_btn = ui.Button(
            label="Erstellen",
            style=discord.ButtonStyle.success,
            emoji="➕"
        )

        async def create_cb(interaction):
            await interaction.response.send_modal(ReminderCreateModal(self))

        create_btn.callback = create_cb

        delete_btn = ui.Button(
            label="Löschen",
            style=discord.ButtonStyle.danger,
            emoji="🗑"
        )

        async def delete_cb(interaction):
            if not self.reminders:
                return await interaction.response.send_message("Keine Erinnerungen.", ephemeral=True)

            options = [
                discord.SelectOption(
                    label=f"ID {rid}",
                    description=grund[:50],
                    value=str(rid)
                )
                for rid, grund, _ in self.reminders
            ]

            select = ui.Select(
                placeholder="Wähle Erinnerung zum Löschen",
                options=options[:25]
            )

            async def select_cb(inter2):
                rid = int(select.values[0])

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "DELETE FROM reminder WHERE id=%s AND userID=%s",
                            (rid, self.user.id)
                        )

                task = self.cog.tasks.pop(rid, None)
                if task:
                    task.cancel()

                await inter2.response.send_message(f"🗑 Erinnerung `{rid}` gelöscht.", ephemeral=True)

            select.callback = select_cb

            view = ui.View()
            view.add_item(select)

            await interaction.response.send_message("Wähle:", view=view, ephemeral=True)

        delete_btn.callback = delete_cb

        refresh_btn = ui.Button(
            label="Aktualisieren",
            style=discord.ButtonStyle.secondary,
            emoji="🔄"
        )

        async def refresh_cb(interaction):
            await self.load()
            self._build()
            await interaction.response.edit_message(view=self)

        refresh_btn.callback = refresh_cb

        container.add_item(ui.ActionRow(create_btn, delete_btn, refresh_btn))

        self.add_item(container)


# =========================================================
#                     COG
# =========================================================

@app_commands.guild_only()
class Reminder(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.tasks = {}

    async def cog_load(self):
        self.bot.loop.create_task(self.load_reminders())

    async def load_reminders(self):
        await self.bot.wait_until_ready()

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, userID, grund, time FROM reminder WHERE time > UNIX_TIMESTAMP()"
                )
                rows = await cur.fetchall()

        for reminder_id, user_id, grund, timestamp in rows:
            when = datetime.fromtimestamp(int(timestamp), timezone.utc)

            task = asyncio.create_task(
                self.reminder_task(reminder_id, user_id, grund, when)
            )
            self.tasks[reminder_id] = task

    async def reminder_task(self, reminder_id, user_id, grund, when):
        await self.bot.wait_until_ready()

        await discord.utils.sleep_until(when)

        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        except:
            return

        embed = discord.Embed(
            title="⏰ Erinnerung",
            description=grund,
            colour=ASTRA_BLUE
        )

        try:
            await user.send(embed=embed)
        except:
            pass

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM reminder WHERE id=%s", (reminder_id,))

        self.tasks.pop(reminder_id, None)

    # =========================================================
    #                     COMMAND
    # =========================================================

    @app_commands.command(name="erinnerungen", description="Öffne den Erinnerungs Manager")
    async def manager(self, interaction: discord.Interaction):

        view = ReminderManagerView(self.bot, self, interaction.user)
        await view.load()

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Reminder(bot))