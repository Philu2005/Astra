import discord
import requests
import json
import random
from waitress import serve
import threading
import httpx
from discord.ext import commands, tasks
from discord.app_commands import AppCommandError
from discord import app_commands
from discord.app_commands import Group
from flask import Flask, request, jsonify
import io
import hashlib
import json
import platform
from zoneinfo import ZoneInfo
import tempfile
from pathlib import Path
from topgg import WebhookManager
import math
import traceback
import asyncio
import topgg
import aiomysql
import jishaku
import os
import logging
import time
from dotenv import load_dotenv
import aiohttp
from datetime import datetime, timezone
from typing import Literal

import re
from threading import Lock

guild_cache = {}
guild_cache_lock = Lock()
bot_ready = False

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

logging.basicConfig(
    level=logging.INFO,  # oder DEBUG für mehr Details
    format="%(asctime)s - %(levelname)s - %(message)s"
)

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.message_content = True
intents.reactions = True


load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
host = os.getenv('DB_HOST')
benutzer = os.getenv('DB_USER')
password_db = os.getenv('DB_PASS')
db_name = os.getenv('DB_NAME')
dbl_token = os.getenv('DBL_TOKEN')
dbl_password = os.getenv('DBL_PASS')
dbl_port = os.getenv('DBL_PORT')

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


class Astra(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="astra!", help_command=None, case_insensitive=True,
                         intents=discord.Intents.all())

        pool: aiomysql.Pool
        self.topggpy = None
        self.task = False
        self.task2 = False
        self.pool = None  # Pool-Objekt hier zentral gespeichert
        self.initial_extensions = [
            "cogs.stats",
            "cogs.birthday",
            "cogs.giveaway",
            "cogs.errors",
            "cogs.notifier",
            "cogs.backups",
            "cogs.help",
            "cogs.goals",
            "cogs.dev",
            "cogs.emojiquiz",
            "cogs.hangman",
            "cogs.economy",
            "cogs.meta",
            "cogs.mod",
            "cogs.astra",
            "cogs.fun",
            "cogs.tempchannel",
            "cogs.afk",
            "cogs.joinrole",
            "cogs.botrole",
            "cogs.reactionrole",
            "cogs.welcome",
            "cogs.leave",
            "cogs.modlog",
            "cogs.autoreact",
            "cogs.warns",
            "cogs.guessthenumber",
            "cogs.counting",
            "cogs.tags",
            "cogs.globalchat",
            "cogs.ticket",
            "cogs.levels",
            "cogs.snake"
        ]

    async def setup_hook(self):
        try:
            self.loop.create_task(rotating_presence(self))
            bot.owner_id = 789555434201677824
            self.topggpy = topgg.DBLClient(self, dbl_token)
            bot.topgg_webhook = topgg.WebhookManager(bot).dbl_webhook("/dblwebhook", dbl_password)
            await bot.topgg_webhook.run(int(dbl_port))
            await self.connect_db()
            await self.init_tables()
            await self.load_cogs()
            self.tree.add_command(Reminder())
            logging.info("Astra ist online!")
            await asyncio.sleep(3)
            logging.info("[PANEL-INFO] Script started!")
            self.keep_alive_task = self.loop.create_task(self.keep_db_alive())
        except Exception as e:
            logging.error(f"❌ Fehler beim Setup:\n{e}")

    async def keep_db_alive(self):
        while True:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")  # Einfacher Testbefehl, um die Verbindung aufrechtzuerhalten
            await asyncio.sleep(120)  # Alle 2 Minuten

    async def connect_db(self):
        """Stellt den DB-Pool her und speichert ihn in self.pool"""
        self.pool = await aiomysql.create_pool(
            host=host,
            port=3306,
            user=benutzer,
            password=password_db,
            db=db_name,
            autocommit=True,
            pool_recycle=3600,
            connect_timeout=5,
            maxsize=50
        )
        logging.info("✅ DB-Verbindung erfolgreich")

    async def init_tables(self):
        """Erstellt/Registriert Tasks und führt einen DB-Healthcheck aus."""
        await run_sql_file(self.pool, SCHEMA_PATH)

        # DB-Healthcheck
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        logging.info("✅ DB erreichbar")

        # Aiomysql anstoßen
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:

                # --- Reminder-Tasks (deine bestehende reminder-Tabelle) ---
                if not self.task:
                    self.task = True
                    # Nur zukünftige Reminder laden; wenn 'time' TEXT ist, trotzdem als int vergleichbar, wenn Unix-Zeit
                    await cur.execute(
                        "SELECT time FROM reminder WHERE time REGEXP '^[0-9]+$' AND CAST(time AS UNSIGNED) > UNIX_TIMESTAMP()")
                    eintraege = await cur.fetchall()

                    async def starte_reminder_tasks():
                        for (t_str,) in eintraege:
                            try:
                                t2 = datetime.fromtimestamp(int(t_str), timezone.utc)
                                asyncio.create_task(funktion(t2))
                                await asyncio.sleep(0.2)
                            except Exception as e:
                                logging.error(f"❌ Reminder-Fehler: {e}")

                    asyncio.create_task(starte_reminder_tasks())

                # --- Vote-Reminder (topgg.next_vote_epoch) ---
                if not self.task2:
                    self.task2 = True

                    await cur.execute("""
                                      SELECT userID, next_vote_epoch
                                      FROM topgg
                                      WHERE next_vote_epoch IS NOT NULL
                                      ORDER BY next_vote_epoch ASC
                                      """)
                    eintraege2 = await cur.fetchall()
                    logging.info(f"[Resume] {len(eintraege2)} offene Vote-Reminder aus DB geladen")

                    async def starte_voterole_tasks():
                        now = datetime.now(timezone.utc)
                        for user_id, ts in eintraege2:
                            try:
                                if not ts:
                                    continue
                                when = datetime.fromtimestamp(int(ts), timezone.utc)
                                if when <= now:
                                    logging.info(f"[Resume] Reminder für {user_id} überfällig – feuere sofort")
                                    when = now
                                else:
                                    logging.info(f"[Resume] Reminder neu geplant für {user_id} um {when.isoformat()}")
                                asyncio.create_task(funktion2(user_id, when))
                                await asyncio.sleep(0.05)
                            except Exception as e:
                                logging.error(f"❌ Reminder-Replay-Fehler (user={user_id}, ts={ts}): {e}")

                    asyncio.create_task(starte_voterole_tasks())

        logging.info("✅ Tasks Registered!")

    async def load_cogs(self):
        """Lädt alle Cogs"""
        geladen, fehler = 0, 0

        # Optional: jishaku laden, aber Fehler ignorieren
        try:
            await self.load_extension("jishaku")
            logging.info("🧪 jishaku erfolgreich geladen")
        except Exception as e:
            logging.error("⚠️  jishaku konnte nicht geladen werden:", e)

        for ext in self.initial_extensions:
            logging.info(f"🔄 Lade: {ext}")
            try:
                await self.load_extension(ext)
                geladen += 1
                logging.info(f"✅ Erfolgreich geladen: {ext}")
            except Exception:
                fehler += 1
                logging.error(f'❌ Fehler beim Laden von: {ext}')
                traceback.print_exc()
                logging.info('---------------------------------------------')

        gesamt = geladen + fehler
        logging.info(f"\n📦 Cogs geladen: {geladen}/{gesamt} erfolgreich ✅")
        if fehler > 0:
            logging.error(f"❗ {fehler} Cog(s) konnten nicht geladen werden.")

    async def on_message(self, msg):
        if msg.author.bot:
            return
        await bot.process_commands(msg)

        botcreated_ts = int(bot.user.created_at.timestamp())

        if msg.content in (f"<@{bot.user.id}>", f"<@!{bot.user.id}>"):
            embed = discord.Embed(
                title="Astra",
                url="https://astra-bot.de/support",
                colour=discord.Colour.blue(),
                description=(
                    f"Hallo Discord! 👋\n"
                    f"Ich bin **Astra**, geboren am <t:{botcreated_ts}:D>. "
                    f"Ich bringe praktische Systeme wie ein Level- und Ticketsystem, Moderationstools, "
                    f"Automod-Schutz, Statistiken, temporäre Sprachkanäle und weitere hilfreiche Funktionen mit. "
                    f"Alle Befehle findest du bequem als **Slash-Befehle** (z. B. `/help`).\n\n"
                    f"Falls du Fragen oder Probleme hast, besuche gerne unseren "
                    f"**[Support-Server ↗](https://astra-bot.de/support)**. "
                    f"Wenn ich dein Interesse geweckt habe, kannst du mich "
                    f"**[hier einladen ↗](https://astra-bot.de/invite)** "
                    f"und direkt ausprobieren 🚀"
                )
            )

            embed.set_author(
                name=str(msg.author),
                icon_url=msg.author.avatar.url if msg.author.avatar else None
            )
            if msg.guild and msg.guild.icon:
                embed.set_thumbnail(url=msg.guild.icon.url)
            embed.set_footer(
                text="Astra Development ©2025 • Mehr Infos auf unserem Support-Server",
                icon_url=msg.guild.icon.url if msg.guild and msg.guild.icon else None
            )

            await msg.channel.send(embed=embed)
            await bot.process_commands(msg)

    @staticmethod
    def find_translatable_strings(path):
        string_regex = re.compile(r'["\'](.*?)["\']')
        translatable = []

        # Ordner cogs durchsuchen
        cogs_path = os.path.join(path, "cogs")
        if os.path.exists(cogs_path):
            for root, dirs, files in os.walk(cogs_path):
                for file in files:
                    if file.endswith(".py"):
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            content = f.read()
                            matches = string_regex.findall(content)
                            for match in matches:
                                if any(word in match.lower() for word in
                                       ["du", "bitte", "nicht", "kannst", "coin", "rolle", "hilfe", "server"]):
                                    translatable.append(match)

        # main.py separat prüfen
        main_py_path = os.path.join(path, "main.py")
        if os.path.isfile(main_py_path):
            with open(main_py_path, "r", encoding="utf-8") as f:
                content = f.read()
                matches = string_regex.findall(content)
                for match in matches:
                    if any(word in match.lower() for word in
                           ["du", "bitte", "nicht", "kannst", "coin", "rolle", "hilfe", "server"]):
                        translatable.append(match)

        return translatable


bot = Astra()


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

async def rotating_presence():
    await bot.wait_until_ready()

    server_count = 0
    member_count = 0
    last_update = 0

    while not bot.is_closed():

        # 🕒 Deutsche Zeit erzwingen
        now = datetime.now(BERLIN_TZ)
        current_time = now.timestamp()

        # 🔄 Stats nur alle 5 Minuten neu berechnen
        if current_time - last_update > 300:
            server_count = len(bot.guilds)
            member_count = sum(g.member_count or 0 for g in bot.guilds)
            last_update = current_time

        # 🇩🇪 Deutsche Tausendertrennung
        server_str = f"{server_count:,}".replace(",", ".")
        member_str = f"{member_count:,}".replace(",", ".")

        # 🌙 Idle zwischen 00:00–06:00 deutscher Zeit
        astra_status = discord.Status.idle if 0 <= now.hour < 6 else discord.Status.online

        activities = [
            discord.Activity(
                type=discord.ActivityType.watching,
                name=f"🔹 {server_str} Server"
            ),
            discord.Activity(
                type=discord.ActivityType.watching,
                name=f"🔹 {member_str} Mitglieder"
            ),
            discord.Activity(
                type=discord.ActivityType.watching,
                name="⚙️ Interaktives Setup"
            ),
            discord.Activity(
                type=discord.ActivityType.watching,
                name="🎫 Modernes Ticket-System"
            ),
        ]

        for activity in activities:
            await bot.change_presence(
                activity=activity,
                status=astra_status
            )
            asyncio.sleep(30)

class VoteView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Auch Voten",
                url="https://top.gg/bot/1113403511045107773/vote",
                emoji=discord.PartialEmoji(name="Herz", id=1361007251434901664)
            )
        )

@bot.event
async def on_dbl_vote(data):
    logging.info(f"on_dbl_vote ausgelöst für User: {data.get('user')}")

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:

            # Test-Hook früh raus
            if data.get("type") == "test":
                return bot.dispatch("dbl_test", data)

            # --- User/Guild/Objekte ---
            user_id = int(data["user"])
            user = bot.get_user(user_id)
            if user is None:
                try:
                    user = await bot.fetch_user(user_id)
                except Exception:
                    logging.error(f"User {user_id} nicht gefunden")
                    return

            guild = bot.get_guild(1141116981697859736)
            if not guild:
                logging.error("Guild nicht gefunden!")
                return

            voterole = guild.get_role(1141116981756575875)
            channel = guild.get_channel(1361006871753789532)

            # --- Zeit/Vote-Logik ---
            now_utc = datetime.now(timezone.utc)
            now_ts = int(now_utc.timestamp())
            next_vote_ts = now_ts + 12 * 3600
            this_month = now_utc.date().replace(day=1)
            vote_increase = 2 if now_utc.weekday() in (4, 5, 6) else 1

            # --- DB lesen ---
            await cur.execute(
                """
                SELECT count, last_reset, last_vote_epoch, streak, best_streak
                FROM topgg
                WHERE userID = %s
                """,
                (user_id,)
            )
            row = await cur.fetchone()

            # --- DUPLICATE-SCHUTZ ---
            if row:
                _, _, last_vote_epoch, _, _ = row
                if last_vote_epoch and now_ts - int(last_vote_epoch) < 60:
                    logging.warning(f"[Vote] Duplicate Vote ignoriert ({user_id})")
                    return

            # =============================
            # USER EXISTIERT NICHT
            # =============================
            if not row:
                member_votes = vote_increase
                streak = 1
                best_streak = 1

                await cur.execute(
                    """
                    INSERT INTO topgg
                        (userID, count, last_reset, last_vote, last_vote_epoch,
                         next_vote_epoch, streak, best_streak)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        member_votes,
                        this_month,
                        now_utc,
                        now_ts,
                        next_vote_ts,
                        streak,
                        best_streak
                    )
                )

            # =============================
            # USER EXISTIERT
            # =============================
            else:
                count, last_reset, last_vote_epoch, streak, best_streak = row

                # Monatsreset
                if not last_reset or last_reset < this_month:
                    count = 0
                    last_reset = this_month

                member_votes = count + vote_increase

                # --- STREAK-LOGIK ---
                diff = now_ts - int(last_vote_epoch)

                if 12 * 3600 <= diff <= 24 * 3600:
                    streak += 1
                else:
                    streak = 1

                if streak > best_streak:
                    best_streak = streak

                await cur.execute(
                    """
                    UPDATE topgg
                    SET
                        count = %s,
                        last_reset = %s,
                        last_vote = %s,
                        last_vote_epoch = %s,
                        next_vote_epoch = %s,
                        streak = %s,
                        best_streak = %s
                    WHERE userID = %s
                    """,
                    (
                        member_votes,
                        last_reset,
                        now_utc,
                        now_ts,
                        next_vote_ts,
                        streak,
                        best_streak,
                        user_id
                    )
                )

            # =============================
            # ECONOMY-REWARD + STREAK-BONUS
            # =============================
            base_amount = random.randint(5, 25)
            streak_bonus = 0

            if streak == 3:
                streak_bonus = 10
            elif streak == 5:
                streak_bonus = 25
            elif streak == 7:
                streak_bonus = 50
            elif streak == 14:
                streak_bonus = 100
            elif streak == 30:
                streak_bonus = 250

            total_amount = base_amount + streak_bonus

            await cur.execute(
                """
                INSERT INTO economy_users (user_id, wallet)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE wallet = wallet + VALUES(wallet)
                """,
                (user_id, total_amount)
            )

            await cur.execute(
                "UPDATE economy_users SET last_work = %s WHERE user_id = %s",
                (now_utc, user_id)
            )

            # --- Gesamtvotes für aktuellen Monat ---
            await cur.execute(
                "SELECT COALESCE(SUM(count), 0) FROM topgg WHERE last_reset = %s",
                (this_month,)
            )
            row = await cur.fetchone()
            total_votes = row[0] if row and row[0] is not None else 0

    # =============================
    # EMBED
    # =============================
    embed = discord.Embed(
        title="Danke fürs Voten von Astra",
        description=(
            f"<:Astra_boost:1141303827107164270> `{user}({user.id})` hat für **Astra** gevotet.\n"
            f"Wir haben nun `{total_votes}` in diesem Monat.\n"
            f"Du hast diesen Monat bereits **{member_votes}** Mal gevotet.\n\n"
            "Du kannst alle 12 Stunden **[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
        ),
        colour=discord.Colour.blue(),
        timestamp=now_utc
    )

    embed.set_thumbnail(
        url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
    )
    embed.set_footer(
        text="Danke für deinen Support",
        icon_url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
    )

    # --- BELohnungstext für Nachricht ---
    if streak_bonus > 0:
        reward_text = (
            f"🔥 **Deine Belohnung:** {base_amount} Coins "
            f"+ {streak_bonus} Streak-Bonus (Streak {streak}) 💰"
        )
    else:
        reward_text = f"🎁 **Deine Belohnung:** {base_amount} Coins 💰"

    member = guild.get_member(user_id)
    if not member:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None

    if member and voterole:
        try:
            await member.add_roles(voterole, reason="Voterole vergeben (Vote erkannt)")
        except Exception as e:
            logging.error(f"Fehler beim Hinzufügen der Rolle an {user_id}: {e}")

    try:
        if channel:
            await channel.send(
                reward_text,
                embed=embed,
                view=VoteView()
            )
    except Exception as e:
        logging.error(f"Fehler beim Senden im Channel: {e}")

    when = datetime.fromtimestamp(next_vote_ts, timezone.utc)
    logging.info(f"[VoteReminder] scheduled DM for {user_id} at {when.isoformat()} (ts={next_vote_ts})")
    asyncio.create_task(funktion2(user_id, when))

    return None




@bot.event
async def on_dbl_test(data):
    """An event that is called whenever someone tests the webhook system for your bot on Top.gg."""
    logging.info(f"on_dbl_test ausgelöst: {data!r}")

    guild = bot.get_guild(1141116981697859736)
    if guild is None:
        logging.error("Guild 1141116981697859736 nicht gefunden")
        return

    channel = guild.get_channel(1361006871753789532)
    if channel is None:
        logging.error("Channel 1361006871753789532 nicht gefunden")
        return

    # User
    user_id = int(data.get("user", 0))
    user = bot.get_user(user_id)
    user_display = f"{user}({user.id})" if user else f"Unbekannt ({user_id})"

    # Bot (Astra)
    astra = bot.get_user(int(data.get("bot", bot.user.id)))

    # Gesamtvotes aus eigener DB für aktuellen Monat
    now_utc = datetime.now(timezone.utc)
    this_month = now_utc.date().replace(day=1)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COALESCE(SUM(count), 0) FROM topgg WHERE last_reset = %s",
                (this_month,)
            )
            row = await cur.fetchone()
            total_votes = row[0] if row and row[0] is not None else 0

    embed = discord.Embed(
        title="Test Vote Erfolgreich",
        description=(
            f"<:Astra_boost:1141303827107164270> `{user_display}` hat für {astra} gevotet.\n"
            f"Wir haben nun `{total_votes}` Votes diesen Monat.\n\n"
            "Du kannst alle 12 Stunden **[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
        ),
        colour=discord.Colour.red(),
        timestamp=now_utc
    )
    embed.set_thumbnail(
        url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
    )
    embed.set_footer(
        text="Danke für deinen Support",
        icon_url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
    )

    msg = await channel.send(embed=embed)
    heart = bot.get_emoji(1361007251434901664)
    if heart:
        await msg.add_reaction(heart)


def all_app_commands(bot):
    global_commands = bot.tree.get_commands()
    from itertools import chain
    guild_commands = chain.from_iterable(bot.tree._guild_commands.values())
    all_commands = list(global_commands) + list(guild_commands)
    # Optional unique machen:
    seen = set()
    unique = []
    for cmd in all_commands:
        sig = (cmd.name, getattr(cmd, "type", None))
        if sig not in seen:
            seen.add(sig)
            unique.append(cmd)
    return unique

@bot.event
async def on_ready():
    with guild_cache_lock:
        guild_cache.clear()
        for g in bot.guilds:
            guild_cache[g.id] = g

    logging.info(f"[CACHE] {len(guild_cache)} Guilds cached")
    servercount = len(bot.guilds)
    usercount = sum(guild.member_count for guild in bot.guilds)
    commandCount = len(all_app_commands(bot))
    channelCount = sum(len(guild.channels) for guild in bot.guilds)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Tabelle erstellen, falls sie noch nicht existiert

            await cur.execute("""
                CREATE TABLE IF NOT EXISTS website_stats (
                    id INT PRIMARY KEY,
                    servercount INT,
                    usercount INT,
                    commandCount INT,
                    channelCount INT
                )
            """)

            # Prüfen, ob Zeile mit id=1 existiert
            await cur.execute("SELECT id FROM website_stats WHERE id=1")
            result = await cur.fetchone()

            if result is None:
                # Wenn nicht, initialen Datensatz anlegen
                await cur.execute(
                    "INSERT INTO website_stats (id, servercount, usercount, commandCount, channelCount) VALUES (1, %s, %s, %s, %s)",
                    (servercount, usercount, commandCount, channelCount)
                )
            else:
                # Ansonsten updaten
                await cur.execute(
                    "UPDATE website_stats SET servercount=%s, usercount=%s, commandCount=%s, channelCount=%s WHERE id=1",
                    (servercount, usercount, commandCount, channelCount)
                )
            global bot_ready
            bot_ready = True
            logging.info("[API] Bot marked as READY")


async def funktion2(user_id: int, when: datetime):
    await bot.wait_until_ready()

    # UTC-sicher
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    logging.info(f"[VoteReminder] task scheduled for {user_id} -> {when.isoformat()}")
    await discord.utils.sleep_until(when)
    now = datetime.now(timezone.utc)
    logging.info(f"[VoteReminder] task woke up for {user_id} at {now.isoformat()}")

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # --- Schutz: ist der Reminder noch gültig? ---
            # Falls der User inzwischen erneut gevotet hat und ein NEUER next_vote_epoch gesetzt wurde,
            # ist dieser Task veraltet und wird übersprungen.
            try:
                await cur.execute("SELECT next_vote_epoch FROM topgg WHERE userID=%s", (user_id,))
                row = await cur.fetchone()
                current_ts = row[0] if row else None
                if current_ts is None:
                    logging.info(f"[VoteReminder] skip {user_id} – next_vote_epoch bereits verbraucht")
                    return
                if current_ts > int(when.timestamp()):
                    logging.info(f"[VoteReminder] skip {user_id} – neuerer Reminder existiert (ts={current_ts})")
                    return
            except Exception as e:
                logging.warning(f"[VoteReminder] Vorab-Check fehlgeschlagen ({user_id}): {e}")

            # --- DM senden ---
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                logging.info(f"[VoteReminder] Versuche DM an {user_id} zu senden...")
                embed = discord.Embed(
                    title="<:Astra_time:1141303932061233202> Du kannst wieder voten!",
                    url="https://top.gg/de/bot/1113403511045107773/vote",
                    description=(
                        "Der Cooldown von 12h ist vorbei. Es wäre schön, wenn du wieder votest.\n"
                        "Als Belohnung erhältst du eine spezielle Rolle auf unserem Support-Server."
                    ),
                    colour=discord.Colour.blue()
                )
                await user.send(embed=embed)
                logging.info(f"[VoteReminder] DM erfolgreich an {user_id} gesendet")
            except Exception as e:
                logging.warning(f"[VoteReminder] ❌ DM an {user_id} fehlgeschlagen: {e}")

            # --- Rolle entfernen (optional) ---
            guild = bot.get_guild(1141116981697859736)
            voterole = guild.get_role(1141116981756575875) if guild else None
            if guild and voterole:
                try:
                    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                except Exception:
                    member = None
                if member and voterole in getattr(member, "roles", []):
                    try:
                        await member.remove_roles(voterole, reason="Voterole Cooldown abgelaufen")
                        logging.info(f"[VoteReminder] Rolle entfernt bei {user_id}")
                    except Exception as e:
                        logging.warning(f"[VoteReminder] Rolle entfernen fehlgeschlagen ({user_id}): {e}")

            # --- Reminder verbrauchen (nur wenn noch derselbe fällig ist) ---
            try:
                await cur.execute(
                    "UPDATE topgg SET next_vote_epoch=NULL "
                    "WHERE userID=%s AND next_vote_epoch <= %s",
                    (user_id, int(when.timestamp()))
                )
            except Exception as e:
                logging.error(f"[VoteReminder] DB-Update fehlgeschlagen ({user_id}): {e}")

        try:
            await conn.commit()
        except Exception:
            pass

    logging.info("[VoteReminder] finished")



async def funktion(when: datetime):
    await bot.wait_until_ready()
    await discord.utils.sleep_until(when=when)
    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT userID, grund FROM reminder")
            result = await cur.fetchall()
            if result == ():
                return
            if result:
                for eintrag in result:
                    userID = eintrag[0]
                    grund = eintrag[1]
                    user = bot.get_user(int(userID))
                    embed = discord.Embed(title="<:Astra_time:1141303932061233202> Erinnerung abgeschlossen.",
                                          description=f"Hier ist deine Erinnerung\n<:Astra_arrow:1141303823600717885> {grund}",
                                          colour=discord.Colour.blue())
                await user.send(embed=embed)
                await cur.execute("DELETE FROM reminder WHERE grund = (%s)", (grund))

@app_commands.guild_only()
class Reminder(app_commands.Group):
    def __init__(self):
        super().__init__(
            name="erinnerung",
            description="Verwalte Erinnerungen."
        )

    @app_commands.command(name="erstellen", description="Setze eine Erinnerung.")
    @app_commands.describe(beschreibung="Beschreibung der Erinnerung.")
    @app_commands.describe(zeit="Wie lange bis zur Erinnerung.")
    async def reminder_set(self, interaction: discord.Interaction, beschreibung: str, zeit: Literal['1m', '3m', '5m', '10m', '20m', '30m', '45m', '1h', '2h', '5h', '10h', '12h', '18h', '1d', '2d', '5d', '6d', '1w', '2w', '4w']):
        """Setze eine Erinnerung."""
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                description = beschreibung
                time = zeit
                await cur.execute("SELECT grund FROM reminder WHERE userID = (%s)",
                                  (interaction.user.id))
                result = await cur.fetchall()
                if result == ():
                    remindid = 1
                    time1 = convert(zeit)  # → float oder int (Sekunden, z. B. 43200 für 12h)
                    t1 = math.floor(discord.utils.utcnow().timestamp() + time1)  # ergibt korrekten Unix-Timestamp
                    t2 = datetime.fromtimestamp(t1, tz=timezone.utc)  # ✅ Zeitzone-aware!
                    asyncio.create_task(funktion(t2))
                    await cur.execute("INSERT INTO reminder(userID, grund, time, remindID) VALUES(%s, %s, %s, %s)",
                                      (interaction.user.id, description, t1, remindid))
                    embed = discord.Embed(
                        title=f"<:Astra_time:1141303932061233202> Erinnerung erstellt (ID {remindid})",
                        description=f"Erinnerung gesetzt auf {discord.utils.format_dt(t2, 'F')}\n<:Astra_arrow:1141303823600717885> {description}",
                        colour=discord.Colour.blue())
                    await interaction.response.send_message(embed=embed)
                if result:
                    time1 = convert(zeit)  # → float oder int (Sekunden, z. B. 43200 für 12h)
                    t1 = math.floor(discord.utils.utcnow().timestamp() + time1)  # ergibt korrekten Unix-Timestamp
                    t2 = datetime.fromtimestamp(t1, tz=timezone.utc)  # ✅ Zeitzone-aware!
                    asyncio.create_task(funktion(t2))
                    await cur.execute("INSERT INTO reminder(userID, grund, time, remindID) VALUES(%s, %s, %s, %s)",
                                      (interaction.user.id, description, t1, len(result) + 1))
                    embed = discord.Embed(
                        title=f"<:Astra_time:1141303932061233202> Erinnerung erstellt (ID {len(result) + 1})",
                        description=f"Erinnerung gesetzt auf {discord.utils.format_dt(t2, 'F')}\n<:Astra_arrow:1141303823600717885> {description}",
                        colour=discord.Colour.blue())
                    await interaction.response.send_message(embed=embed)

    @app_commands.command(name="anzeigen", description="Zeigt alle Erinnerungen an.")
    async def reminder_list(self, interaction: discord.Interaction):
        """Zeigt eine Liste aller gesetzten Erinnerungen."""
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                memberid = interaction.user.id
                member = interaction.user
                await cur.execute("SELECT grund, remindID, time FROM reminder WHERE userID = (%s)",
                                  (interaction.user.id))
                result = await cur.fetchall()
                if result == ():
                    embed2 = discord.Embed(title=f"Alle Erinnerungen von {member}, {memberid}",
                                           description=f"{member.name} hat zur Zeit keine aktiven Erinnerungen.",
                                           color=discord.Color.blue())
                    await interaction.response.send_message(embed=embed2)

                else:
                    embed = discord.Embed(title=f"Alle Erinnerungen von {member.name}, {memberid}",
                                          description=f"Um eine Erinnerung zu setzen, nutze den Befehl `/erinnerung erstellen`.",
                                          color=discord.Color.blue(), timestamp=discord.utils.utcnow())
                    embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
                    for eintrag in result:
                        reason = eintrag[0]
                        warnID = eintrag[1]
                        time = eintrag[2]
                        embed.add_field(name=f"ID: {warnID}",
                                        value=f"<:Astra_arrow:1141303823600717885>: {reason}\n<:Astra_time:1141303932061233202> Endet: <t:{time}:F>",
                                        inline=True)

                    await interaction.response.send_message(embed=embed)

    @app_commands.command(name="löschen", description="Löscht eine Erinnerung.")
    @app_commands.describe(id="Die ID der Erinnerung, die gelöscht werden soll.")
    async def reminder_delete(self, interaction: discord.Interaction, id: int):
        """Löscht eine gespeicherte Erinnerung anhand der ID."""
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                member = interaction.user
                await cur.execute("SELECT remindID FROM reminder WHERE userID = (%s)", (interaction.user.id))
                result = await cur.fetchall()

                if result:
                    await cur.execute("DELETE FROM reminder WHERE userID = (%s) AND remindID = (%s)",
                                      (member.id, id))
                    embed2 = discord.Embed(title="Erinnerung Gelöscht",
                                           description=f"Die Erinnerung mit der ID ``{id}`` wurde gelöscht.",
                                           color=discord.Color.green())
                    await interaction.response.send_message(embed=embed2)
                if not result:
                    embed2 = discord.Embed(title="Keine Erinnerung gefunden",
                                           description=f"Es gibt keine Aktive Erinnerung mit der ID: ``{id}``.",
                                           color=discord.Color.green())
                    await interaction.response.send_message(embed=embed2)


@bot.command()
@commands.guild_only()
@commands.is_owner()
async def advert(ctx):
    embed = discord.Embed(title="`🎃` Astra x Astra Support",
                          url="https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands",
                          description="Astra ist der einzige Bot, den Sie zur Verwaltung Ihres gesamten Servers benötigen. Es gibt viele Server, die Astra verwenden. Vielleicht sind Sie der Nächste?\n\n> __**Was bieten wir an?**__\n・<:Astra_ticket:1141833836204937347> Öffentliches Ticketsystem für Ihren Server\n・<:Astra_time:1141303932061233202> Automatische Moderation\n・<:Astra_messages:1141303867850641488> Willkommen/Nachrichten hinterlassen\n・<:Astra_settings:1141303908778639490> Joinrole&Botrole\n・<:Astra_herz:1141303857855594527> Reaktionsrollen\n・<:Astra_global1:1141303843993436200> Globalchat\n\n\n> __**Nützliche Links:**__\n・[Astra einladen ➚](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n・[Support erhalten ➚](https://discord.gg/eatdJPfjWc)",colour=discord.Colour.blue())
    embed.set_image(
        url="https://cdn.discordapp.com/attachments/842039934142513152/879880068262940672/Astra-premium3.gif")
    embed.set_thumbnail(url=ctx.guild.icon.url)
    msg = await ctx.send("https://discord.gg/eatdJPfjWc", embed=embed)
    await ctx.message.delete()


@bot.command()
@commands.is_owner()
async def sync(ctx, serverid: int = None):
    """Synchronisiere bestimmte Commands."""
    if serverid is None:
        try:
            s = await bot.tree.sync()
            a = 0
            for command in s:
                a += 1
            globalembed = discord.Embed(color=discord.Color.orange(), title="Synchronisierung",
                                        description=f"Die Synchronisierung von `{a} Commands` wurde eingeleitet.\nEs wird ungefähr eine Stunde dauern, damit sie global angezeigt werden.")
            await ctx.send(embed=globalembed)
        except Exception as e:
            await ctx.send(f"**❌ Synchronisierung fehlgeschlagen**\n```\n{e}```")

    if serverid is not None:
        guild = bot.get_guild(int(serverid))
        if guild:
            try:
                s = await bot.tree.sync(guild=discord.Object(id=guild.id))
                a = 0
                for command in s:
                    a += 1
                localembed = discord.Embed(color=discord.Color.orange(), title="Synchronisierung",
                                           description=f"Die Synchronisierung von `{a} Commands` ist fertig.\nEs wird nur maximal eine Minute dauern, weil sie nur auf dem Server {guild.name} synchronisiert wurden.")
                await ctx.send(embed=localembed)
            except Exception as e:
                await ctx.send(f"**❌ Synchronisierung fehlgeschlagen**\n```\n{e}```")
        if guild is None:
            await ctx.send(f"❌ Der Server mit der ID `{serverid}` wurde nicht gefunden.")

def serialize_guild(guild: discord.Guild):
    return {
        "id": str(guild.id).strip(),
        "name": guild.name,
        "icon": guild.icon.key if guild.icon else None,
        "memberCount": guild.member_count
    }


app = Flask(__name__)

@app.route('/status')
def status():
    return jsonify(online=True)

@app.route('/servers')
def servers():
    if not bot.is_ready():
        return jsonify(success=False, error="Bot not ready"), 503

    with guild_cache_lock:
        servers = [serialize_guild(g) for g in guild_cache.values()]

    return jsonify(
        success=True,
        count=len(servers),
        servers=servers
    )

@app.route('/servers/<int:guild_id>')
def server_detail(guild_id):
    if not bot_ready:
        return jsonify(success=False, error="Bot not ready"), 503
    with guild_cache_lock:
        guild = guild_cache.get(guild_id)

    if not guild:
        return jsonify(
            success=False,
            error="Server not found"
        ), 404

    return jsonify(
        success=True,
        server={
            "id": str(guild.id),
            "name": guild.name,
            "icon": guild.icon.key if guild.icon else None,
            "memberCount": guild.member_count,
            "channelCount": len(guild.channels),
            "roleCount": len(guild.roles),
            "ownerId": str(guild.owner_id)
        }
    )

@app.route('/servers/<int:guild_id>/roles')
def server_roles(guild_id):
    if not bot_ready:
        return jsonify(success=False, error="Bot not ready"), 503

    with guild_cache_lock:
        guild = guild_cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    roles = [
        {
            "id": str(role.id),
            "name": role.name
        }
        for role in guild.roles
        if role.name != "@everyone"
    ]

    return jsonify(
        success=True,
        count=len(roles),
        roles=roles
    )



def run_flask():
    serve(app, host="localhost", port=5000)  # produktionsreif, keine Warning

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
