import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from cogs.economy import EconomyMixin

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

JOBS = [
    {
        "name": "Küchenhilfe",
        "req": 0,
        "desc": "\nVerdiene zwischen 20 und 30 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **0** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [20, 30],
    },
    {
        "name": "Kassierer",
        "req": 5,
        "desc": "\nVerdiene zwischen 30 und 40 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **5** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [30, 40],
    },
    {
        "name": "Kebap-Mann",
        "req": 10,
        "desc": "\nVerdiene zwischen 40 und 50 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **10** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [40, 50],
    },
    {
        "name": "Elektroniker",
        "req": 15,
        "desc": "\nVerdiene zwischen 50 und 60 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **15** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [50, 60],
    },
    {
        "name": "Betreuer",
        "req": 20,
        "desc": "\nVerdiene zwischen 60 und 70 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **20** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [60, 70],
    },
    {
        "name": "Bäcker",
        "req": 25,
        "desc": "\nVerdiene zwischen 70 und 80 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **25** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [70, 80],
    },
    {
        "name": "Bauarbeiter",
        "req": 30,
        "desc": "\nVerdiene zwischen 80 und 90 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **30** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [80, 90],
    },
    {
        "name": "Gärtner",
        "req": 35,
        "desc": "\nVerdiene zwischen 90 und 100 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **35** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [90, 100],
    },
    {
        "name": "Lehrer",
        "req": 40,
        "desc": "\nVerdiene zwischen 100 und 110 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **40** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [100, 110],
    },
    {
        "name": "Koch",
        "req": 45,
        "desc": "\nVerdiene zwischen 110 und 120 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **45** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [110, 120],
    },
    {
        "name": "Sanitäter",
        "req": 50,
        "desc": "\nVerdiene zwischen 120 und 130 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **50** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [120, 130],
    },
    {
        "name": "TV-Moderator",
        "req": 60,
        "desc": "\nVerdiene zwischen 130 und 140 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **60** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [130, 140],
    },
    {
        "name": "Schauspieler",
        "req": 70,
        "desc": "\nVerdiene zwischen 140 und 150 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **70** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [140, 150],
    },
    {
        "name": "Ingenieur",
        "req": 80,
        "desc": "\nVerdiene zwischen 140 und 150 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **80** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [150, 160],
    },
    {
        "name": "Streamer",
        "req": 90,
        "desc": "\nVerdiene zwischen 160 und 170 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **90** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [160, 170],
    },
    {
        "name": "Athlet",
        "req": 100,
        "desc": "\nVerdiene zwischen 170 und 180 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **100** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [170, 180],
    },
    {
        "name": "Polizist",
        "req": 120,
        "desc": "\nVerdiene zwischen 180 und 190 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **120** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [180, 190],
    },
    {
        "name": "Programmierer",
        "req": 140,
        "desc": "\nVerdiene zwischen 190 und 200 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **140** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [190, 200],
    },
    {
        "name": "Chirurg",
        "req": 160,
        "desc": "\nVerdiene zwischen 170 und 180 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **160** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [220, 240],
    },
    {
        "name": "Chefarzt",
        "req": 180,
        "desc": "\nVerdiene zwischen 240 und 250 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **180** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [240, 250],
    },
    {
        "name": "Rechtsanwalt",
        "req": 200,
        "desc": "\nVerdiene zwischen 250 und 260 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **200** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [250, 260],
    },
    {
        "name": "Unternehmensleiter",
        "req": 250,
        "desc": "\nVerdiene zwischen 260 und 270 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **250** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [260, 270],
    },
    {
        "name": "Richter",
        "req": 300,
        "desc": "\nVerdiene zwischen 270 und 280 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **300** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [270, 300],
    },
    {
        "name": "Astronaut",
        "req": 350,
        "desc": "\nVerdiene zwischen 300 und 310 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **400** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [300, 330],
    },
    {
        "name": "Pilot",
        "req": 400,
        "desc": "\nVerdiene zwischen 300 und 310 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **400** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [330, 400],
    },
    {
        "name": "Wissenschaftler",
        "req": 450,
        "desc": "\nVerdiene zwischen 410 und 430 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **450** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [410, 430],
    },
    {
        "name": "Professor",
        "req": 500,
        "desc": "\nVerdiene zwischen 440 und 460 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **500** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [440, 460],
    },
    {
        "name": "Pharmaforscher",
        "req": 550,
        "desc": "\nVerdiene zwischen 470 und 490 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **550** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [470, 490],
    },
    {
        "name": "Bankmanager",
        "req": 600,
        "desc": "\nVerdiene zwischen 500 und 530 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **600** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [500, 530],
    },
    {
        "name": "Politiker",
        "req": 650,
        "desc": "\nVerdiene zwischen 530 und 560 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **650** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [530, 560],
    },
    {
        "name": "Unternehmensberater",
        "req": 700,
        "desc": "\nVerdiene zwischen 560 und 590 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **700** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [560, 590],
    },
    {
        "name": "Chefredakteur",
        "req": 750,
        "desc": "\nVerdiene zwischen 590 und 620 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **750** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [590, 620],
    },
    {
        "name": "Finanzanalyst",
        "req": 800,
        "desc": "\nVerdiene zwischen 620 und 650 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **800** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [620, 650],
    },
    {
        "name": "Medienproduzent",
        "req": 850,
        "desc": "\nVerdiene zwischen 650 und 680 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **850** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [650, 680],
    },
    {
        "name": "Entwicklungsleiter",
        "req": 900,
        "desc": "\nVerdiene zwischen 680 und 710 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **900** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [680, 710],
    },
    {
        "name": "Regierungsberater",
        "req": 1000,
        "desc": "\nVerdiene zwischen 710 und 750 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **1000** Stunden gearbeitet haben, um diesen Job freizuschalten.",
        "amt": [710, 750],
    },
]


class JobListView(discord.ui.View):
    def __init__(self, jobs, user_hours):
        super().__init__()
        self.jobs = jobs
        self.user_hours = user_hours
        self.page = 0
        self.items_per_page = 5

    def generate_job_embed(self):
        embed = discord.Embed(
            title="<:Astra_file1:1141303837181886494> Jobliste",
            color=discord.Color.blue(),
        )
        start_idx = self.page * self.items_per_page
        end_idx = start_idx + self.items_per_page

        for job in self.jobs[start_idx:end_idx]:
            locked = self.user_hours < job["req"]
            status = (
                "<:Astra_locked:1141824745243942912> Gesperrt"
                if locked
                else "<:Astra_unlock:1141824750851731486> Verfügbar"
            )
            embed.add_field(
                name=f"{job['name']} ({status})",
                value=f"{job['desc']}\nBenötigte Stunden: **{job['req']}**",
                inline=False,
            )

        total_pages = (len(self.jobs) + self.items_per_page - 1) // self.items_per_page
        embed.set_footer(text=f"Seite {self.page + 1} von {total_pages}")
        return embed

    @discord.ui.button(
        label="Zurück",
        style=discord.ButtonStyle.primary,
        emoji="<:Astra_arrow_backwards:1392540551546671348>",
        row=0,
    )
    async def previous_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(
                embed=self.generate_job_embed(), view=self
            )

    @discord.ui.button(
        label="Weiter",
        style=discord.ButtonStyle.primary,
        emoji="<:Astra_arrow:1141303823600717885>",
        row=0,
    )
    async def next_page_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if (self.page + 1) * self.items_per_page < len(self.jobs):
            self.page += 1
            await interaction.response.edit_message(
                embed=self.generate_job_embed(), view=self
            )

    @discord.ui.button(label="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def go_home(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.page != 0:
            self.page = 0
            await interaction.response.edit_message(
                embed=self.generate_job_embed(), view=self
            )


@app_commands.guild_only()
class JobGroup(EconomyMixin, app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(name="job", description="Alles rund um deinen Job")

    @app_commands.command(name="work", description="Arbeite in deinem aktuellen Job.")
    async def work(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = await self.get_user(user_id)
        job_name = user_data[2]
        last_work = user_data[4]
        logging.info(f"RAW last_work from DB: {last_work}")

        if not job_name:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast keinen Job. Nutze `/job apply`, um einen Job zu wählen.",
                ephemeral=True,
            )
            return

        now = datetime.now(timezone.utc)
        if last_work and last_work.tzinfo is None:
            last_work = last_work.replace(tzinfo=timezone.utc)

        if last_work and now < last_work + timedelta(hours=8):
            remaining = (last_work + timedelta(hours=8)) - now
            total_seconds = int(remaining.total_seconds())
            hours_left, remainder = divmod(total_seconds, 3600)
            minutes_left, seconds_left = divmod(remainder, 60)
            parts = []
            if hours_left:
                parts.append(f"{hours_left}h")
            if minutes_left:
                parts.append(f"{minutes_left}m")
            if seconds_left or not parts:
                parts.append(f"{seconds_left}s")

            logging.info(f"NOW: {now}")
            logging.info(f"LAST_WORK: {last_work}")
            logging.info(f"DIFF: {now - last_work if last_work else None}")

            await interaction.response.send_message(
                f"<:Astra_time:1141303932061233202> Du musst noch **{' '.join(parts)}** warten, bevor du wieder arbeiten kannst.",
                ephemeral=True,
            )
            return

        job = next((entry for entry in JOBS if entry["name"] == job_name), None)
        if not job:
            await interaction.response.send_message(
                "Fehler: Dein Job wurde nicht gefunden.", ephemeral=True
            )
            return

        earned = random.randint(*job["amt"])
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, hours_worked = hours_worked + 1, last_work = %s WHERE user_id = %s",
                    (earned, now, user_id),
                )

        await interaction.response.send_message(
            f"<:Astra_time:1141303932061233202> Du hast 1 Stunde als **{job_name}** gearbeitet und {earned} <:Coin:1359178077011181811> verdient!"
        )

    @app_commands.command(name="list", description="Zeigt die Jobliste.")
    async def job_list(self, interaction: discord.Interaction):
        user_hours = (await self.get_user(interaction.user.id))[3]
        view = JobListView(JOBS, user_hours)
        await interaction.response.send_message(
            embed=view.generate_job_embed(), view=view
        )

    @app_commands.command(
        name="apply", description="Bewirb dich auf einen verfügbaren Job."
    )
    @app_commands.describe(name="Name des Jobs, den du annehmen möchtest.")
    async def job_apply(self, interaction: discord.Interaction, name: str):
        user_hours = (await self.get_user(interaction.user.id))[3]
        job = next(
            (entry for entry in JOBS if entry["name"].lower() == name.lower()), None
        )

        if not job:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Dieser Job existiert nicht.",
                ephemeral=True,
            )
            return
        if user_hours < job["req"]:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast noch nicht genug Stunden gearbeitet, um diesen Job zu bekommen.",
                ephemeral=True,
            )
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET job = %s WHERE user_id = %s",
                    (job["name"], interaction.user.id),
                )

        await interaction.response.send_message(
            f"<:Astra_accept:1141303821176422460> Du arbeitest jetzt als **{job['name']}**!"
        )

    @app_commands.command(name="quit", description="Kündige deinen aktuellen Job.")
    async def job_quit(self, interaction: discord.Interaction):
        if not (await self.get_user(interaction.user.id))[2]:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast momentan keinen Job.",
                ephemeral=True,
            )
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET job = NULL WHERE user_id = %s",
                    (interaction.user.id,),
                )

        await interaction.response.send_message(
            "<:Astra_accept:1141303821176422460> Du hast deinen Job erfolgreich gekündigt."
        )


async def setup(bot):
    bot.tree.add_command(JobGroup(bot))
