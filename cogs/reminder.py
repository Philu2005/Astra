import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import math
from datetime import datetime, timezone


def convert(time):
    pos = ["s", "m", "h", "d", "w"]
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24, "w": 3600 * 24 * 7}
    unit = time[-1]
    if unit not in pos:
        return -1
    try:
        val = int(time[:-1])
    except Exception:
        return -2
    return val * time_dict[unit]

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

        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

        await discord.utils.sleep_until(when)

        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                return

        embed = discord.Embed(
            title="<:Astra_time:1141303932061233202> Erinnerung abgeschlossen.",
            description=f"Hier ist deine Erinnerung\n<:Astra_arrow:1141303823600717885> {grund}",
            colour=discord.Colour.blue()
        )

        try:
            await user.send(embed=embed)
        except Exception:
            pass

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM reminder WHERE id = %s",
                    (reminder_id,)
                )

        self.tasks.pop(reminder_id, None)

    # ---------------- SLASH COMMANDS ---------------- #

    reminder = app_commands.Group(
        name="erinnerung",
        description="Verwalte Erinnerungen."
    )

    @reminder.command(name="erstellen", description="Setze eine Erinnerung.")
    @app_commands.describe(
        beschreibung="Beschreibung der Erinnerung.",
        zeit="Wie lange bis zur Erinnerung."
    )
    async def reminder_set(
        self,
        interaction: discord.Interaction,
        beschreibung: str,
        zeit: str
    ):
        seconds = convert(zeit)

        if seconds < 0:
            return await interaction.response.send_message(
                "❌ Ungültige Zeit!",
                ephemeral=True
            )

        t1 = math.floor(discord.utils.utcnow().timestamp() + seconds)
        t2 = datetime.fromtimestamp(t1, tz=timezone.utc)

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO reminder(userID, grund, time) VALUES(%s, %s, %s)",
                    (interaction.user.id, beschreibung, t1)
                )
                reminder_id = cur.lastrowid

        task = asyncio.create_task(
            self.reminder_task(reminder_id, interaction.user.id, beschreibung, t2)
        )
        self.tasks[reminder_id] = task

        embed = discord.Embed(
            title=f"<:Astra_time:1141303932061233202> Erinnerung erstellt (ID {reminder_id})",
            description=f"Erinnerung gesetzt auf {discord.utils.format_dt(t2, 'F')}\n<:Astra_arrow:1141303823600717885> {beschreibung}",
            colour=discord.Colour.blue()
        )

        await interaction.response.send_message(embed=embed)

    @reminder.command(name="anzeigen", description="Zeigt alle Erinnerungen an.")
    async def reminder_list(self, interaction: discord.Interaction):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT grund, id, time FROM reminder WHERE userID = %s",
                    (interaction.user.id,)
                )
                result = await cur.fetchall()

        if not result:
            embed = discord.Embed(
                title=f"Alle Erinnerungen von {interaction.user}",
                description=f"{interaction.user.name} hat zur Zeit keine aktiven Erinnerungen.",
                color=discord.Color.blue()
            )
            return await interaction.response.send_message(embed=embed)

        embed = discord.Embed(
            title=f"Alle Erinnerungen von {interaction.user.name}",
            description="Um eine Erinnerung zu setzen, nutze den Befehl `/erinnerung erstellen`.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(
            name=interaction.user,
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None
        )

        for eintrag in result:
            reason = eintrag[0]
            remindID = eintrag[1]
            time = eintrag[2]

            embed.add_field(
                name=f"ID: {remindID}",
                value=f"<:Astra_arrow:1141303823600717885>: {reason}\n<:Astra_time:1141303932061233202> Endet: <t:{time}:F>",
                inline=True
            )

        await interaction.response.send_message(embed=embed)
        return None

    @reminder.command(name="löschen", description="Löscht eine Erinnerung.")
    @app_commands.describe(id="Die ID der Erinnerung, die gelöscht werden soll.")
    async def reminder_delete(self, interaction: discord.Interaction, id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM reminder WHERE userID = %s AND id = %s",
                    (interaction.user.id, id)
                )
                result = await cur.fetchone()

                if not result:
                    embed = discord.Embed(
                        title="Keine Erinnerung gefunden",
                        description=f"Es gibt keine aktive Erinnerung mit der ID: `{id}`.",
                        color=discord.Color.red()
                    )
                    return await interaction.response.send_message(embed=embed)

                await cur.execute(
                    "DELETE FROM reminder WHERE userID = %s AND id = %s",
                    (interaction.user.id, id)
                )

        task = self.tasks.pop(id, None)
        if task:
            task.cancel()

        embed = discord.Embed(
            title="Erinnerung gelöscht",
            description=f"Die Erinnerung mit der ID `{id}` wurde gelöscht.",
            color=discord.Color.green()
        )

        await interaction.response.send_message(embed=embed)
        return None


async def setup(bot):
    await bot.add_cog(Reminder(bot))