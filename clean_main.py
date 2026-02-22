# ============================================================
# ======================== IMPORTS ===========================
# ============================================================

# Discord / Bot
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.app_commands import AppCommandError, Group

# HTTP / Web
import requests
import httpx
import aiohttp

# Webserver
from flask import Flask, request, jsonify
from waitress import serve

# Datenbank
import aiomysql

# Top.gg
import topgg
from topgg import WebhookManager

# Async / Threading
import asyncio
import threading

# Standard Library
import os
import io
import re
import json
import math
import time
import hashlib
import random
import logging
import traceback
import tempfile
import platform
import datetime
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# Debug / Dev
import jishaku
from dotenv import load_dotenv


# ============================================================
# ===================== KONFIGURATION ========================
# ============================================================

# Pfad zur SQL-Datei mit Tabellenstruktur
SCHEMA_PATH = "/root/Astra/opt/schema.sql"


# ============================================================
# ===================== SQL HELPER ===========================
# ============================================================

async def run_sql_file(pool, path: str):
    """
    Führt eine SQL-Datei aus:
    - entfernt Kommentare
    - splittet Statements
    - führt sie einzeln aus
    """
    p = Path(path)
    if not p.exists():
        logging.error(f"[DB] SQL-Datei nicht gefunden: {path}")
        return

    raw = p.read_text(encoding="utf-8")

    # Block-Kommentare entfernen (/* ... */)
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)

    # Zeilen-Kommentare entfernen (-- ...)
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"--.*$", "", line)
        lines.append(line)

    cleaned = "\n".join(lines)

    # Statements trennen
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for stmt in statements:
                try:
                    await cur.execute(stmt)
                except Exception as e:
                    logging.error(f"[DB] Fehler in Statement:\n{stmt}\n{e}")


# ============================================================
# ======================== LOGGING ===========================
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ============================================================
# ======================= DISCORD ============================
# ============================================================

# Discord Intents
intents = discord.Intents.default()
intents.message_content = True


# ============================================================
# ===================== ENV VARS =============================
# ============================================================

# .env laden
load_dotenv()

# Discord
TOKEN = os.getenv('DISCORD_TOKEN')

# Datenbank
host = os.getenv('DB_HOST')
benutzer = os.getenv('DB_USER')
password_db = os.getenv('DB_PASS')
db_name = os.getenv('DB_NAME')

# Top.gg
dbl_token = os.getenv('DBL_TOKEN')
dbl_password = os.getenv('DBL_PASS')
dbl_port = os.getenv('DBL_PORT')


# ============================================================
# ===================== HELPER FUNKTIONEN ====================
# ============================================================

def convert(time):
    """
    Wandelt Zeitstrings (z.B. 1m, 2h, 1d) in Sekunden um
    """
    pos = ["s", "m", "h", "d", "w"]
    time_dict = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 3600 * 24,
        "w": 3600 * 24 * 7
    }

    unit = time[-1]
    if unit not in pos:
        return -1

    try:
        val = int(time[:-1])
    except Exception:
        return -2

    return val * time_dict[unit]

# ============================================================
# ========================= BOT ==============================
# ============================================================

class Astra(commands.Bot):
    """
    Haupt-Bot-Klasse
    """

    def __init__(self):
        super().__init__(
            command_prefix="astra!",
            help_command=None,
            case_insensitive=True,
            intents=discord.Intents.all()
        )

        # Top.gg Client
        self.topggpy = None

        # Task-Flags (verhindert doppeltes Starten)
        self.task = False
        self.task2 = False

        # MySQL Pool
        self.pool = None

        # Alle Cogs
        self.initial_extensions = [
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
            "cogs.blacklist",
            "cogs.warns",
            "cogs.guessthenumber",
            "cogs.counting",
            "cogs.tags",
            "cogs.capslock",
            "cogs.globalchat",
            "cogs.ticket",
            "cogs.levels",
            "cogs.snake"
        ]

    # ========================================================
    # ==================== SETUP HOOK ========================
    # ========================================================

    async def setup_hook(self):
        """
        Wird einmal beim Bot-Start ausgeführt
        """
        try:
            # Owner-ID setzen
            bot.owner_id = 789555434201677824

            # Top.gg initialisieren
            self.topggpy = topgg.DBLClient(self, dbl_token)
            bot.topgg_webhook = topgg.WebhookManager(bot).dbl_webhook(
                "/dblwebhook",
                dbl_password
            )
            await bot.topgg_webhook.run(int(dbl_port))

            # Datenbank verbinden & Tabellen laden
            await self.connect_db()
            await self.init_tables()

            # Cogs laden
            await self.load_cogs()

            # Reminder Slash-Gruppe registrieren
            self.tree.add_command(Reminder())

            logging.info("Astra ist online!")
            await asyncio.sleep(3)
            logging.info("[PANEL-INFO] Script started!")

            # Keep-Alive Task für DB
            self.keep_alive_task = self.loop.create_task(self.keep_db_alive())

        except Exception as e:
            logging.error(f"❌ Fehler beim Setup:\n{e}")

    # ========================================================
    # ================= DB KEEP ALIVE ========================
    # ========================================================

    async def keep_db_alive(self):
        """
        Führt regelmäßig einen DB-Test aus,
        damit die Verbindung nicht geschlossen wird
        """
        while True:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
            await asyncio.sleep(120)

    # ========================================================
    # ================= DB CONNECT ===========================
    # ========================================================

    async def connect_db(self):
        """
        Erstellt den aiomysql Connection Pool
        """
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

    # ========================================================
    # ================= INIT TABLES =========================
    # ========================================================

    async def init_tables(self):
        """
        Initialisiert Tabellen & startet gespeicherte Tasks
        """
        # SQL-Schema laden
        await run_sql_file(self.pool, SCHEMA_PATH)

        # DB Healthcheck
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        logging.info("✅ DB erreichbar")

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:

                # ================= REMINDER TASKS =================

                if not self.task:
                    self.task = True

                    await cur.execute(
                        "SELECT time FROM reminder "
                        "WHERE time REGEXP '^[0-9]+$' "
                        "AND CAST(time AS UNSIGNED) > UNIX_TIMESTAMP()"
                    )
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

                # ================= VOTE REMINDER TASKS =================

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
                                    when = now

                                asyncio.create_task(funktion2(user_id, when))
                                await asyncio.sleep(0.05)
                            except Exception as e:
                                logging.error(
                                    f"❌ Reminder-Replay-Fehler (user={user_id}, ts={ts}): {e}"
                                )

                    asyncio.create_task(starte_voterole_tasks())

        logging.info("✅ Tasks Registered!")

    # ========================================================
    # ================= LOAD COGS ============================
    # ========================================================

    async def load_cogs(self):
        """
        Lädt alle Extensions / Cogs
        """
        geladen = 0
        fehler = 0

        # Jishaku optional
        try:
            await self.load_extension("jishaku")
            logging.info("🧪 jishaku erfolgreich geladen")
        except Exception as e:
            logging.error("⚠️ jishaku konnte nicht geladen werden:", e)

        for ext in self.initial_extensions:
            logging.info(f"🔄 Lade: {ext}")
            try:
                await self.load_extension(ext)
                geladen += 1
                logging.info(f"✅ Erfolgreich geladen: {ext}")
            except Exception:
                fehler += 1
                logging.error(f"❌ Fehler beim Laden von: {ext}")
                traceback.print_exc()
                logging.info('---------------------------------------------')

        gesamt = geladen + fehler
        logging.info(f"\n📦 Cogs geladen: {geladen}/{gesamt} erfolgreich")
        if fehler > 0:
            logging.error(f"❗ {fehler} Cog(s) konnten nicht geladen werden.")


# ============================================================
# ================== BOT INITIALISIERUNG =====================
# ============================================================

bot = Astra()


# ============================================================
# ===================== LOGGING (DEBUG) =====================
# ============================================================

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# ============================================================
# ===================== MESSAGE EVENT =======================
# ============================================================

@bot.event
async def on_message(msg):
    """
    Wird bei jeder Nachricht ausgelöst
    """
    if msg.author.bot:
        return

    # Normale Commands weiterleiten
    await bot.process_commands(msg)

    # Bot-Erstellungszeit
    botcreated_ts = int(bot.user.created_at.timestamp())

    # Ping auf Bot (@Astra)
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


# ============================================================
# =========== STRING SCANNER (ÜBERSETZUNGEN) =================
# ============================================================

def find_translatable_strings(path):
    """
    Sucht Strings in Cogs & main.py, die potentiell übersetzt werden sollen
    """
    string_regex = re.compile(r'["\'](.*?)["\']')
    translatable = []

    # Cogs durchsuchen
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

    # main.py prüfen
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


# ============================================================
# ======================== VOTEVIEW ==========================
# ============================================================

class VoteView(discord.ui.View):
    """
    Button-View für Vote-Embeds
    """

    def __init__(self):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Auch Voten",
                url="https://top.gg/bot/1113403511045107773/vote",
                emoji=discord.PartialEmoji(
                    name="Herz",
                    id=1361007251434901664
                )
            )
        )

# ============================================================
# ===================== TOP.GG VOTE EVENT ====================
# ============================================================

@bot.event
async def on_dbl_vote(data):
    """
    Wird ausgelöst, wenn ein User auf Top.gg für den Bot votet
    """
    logging.info(f"on_dbl_vote ausgelöst für User: {data.get('user')}")

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:

            # Test-Vote direkt weiterleiten
            if data.get("type") == "test":
                return bot.dispatch("dbl_test", data)

            # ================= USER / GUILD ===================

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

            # ================= ZEIT LOGIK =====================

            now_utc = datetime.now(timezone.utc)
            now_ts = int(now_utc.timestamp())
            next_vote_ts = now_ts + 12 * 3600
            this_month = now_utc.date().replace(day=1)

            # Wochenende = doppelte Votes
            vote_increase = 2 if now_utc.weekday() in [4, 5, 6] else 1

            # ================= DB UPDATE =====================

            await cur.execute(
                "SELECT count, last_reset FROM topgg WHERE userID = %s",
                (user_id,)
            )
            row = await cur.fetchone()

            if not row:
                member_votes = vote_increase
                await cur.execute(
                    """
                    INSERT INTO topgg
                    (userID, count, last_reset, last_vote, last_vote_epoch, next_vote_epoch)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, member_votes, this_month, now_utc, now_ts, next_vote_ts)
                )
            else:
                count, last_reset = row
                if not last_reset or last_reset < this_month:
                    count = 0
                member_votes = count + vote_increase
                await cur.execute(
                    """
                    UPDATE topgg
                    SET count=%s,
                        last_reset=%s,
                        last_vote=%s,
                        last_vote_epoch=%s,
                        next_vote_epoch=%s
                    WHERE userID=%s
                    """,
                    (member_votes, this_month, now_utc, now_ts, next_vote_ts, user_id)
                )

            # ================= GESAMT VOTES ==================

            await cur.execute(
                "SELECT COALESCE(SUM(count), 0) FROM topgg WHERE last_reset = %s",
                (this_month,)
            )
            row = await cur.fetchone()
            total_votes = row[0] if row and row[0] is not None else 0

    # ================= EMBED ================================

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

    # ================= ROLLE VERGEBEN =======================

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
            logging.error(f"Fehler beim Hinzufügen der Rolle: {e}")

    # ================= POST IM CHANNEL =====================

    try:
        if channel:
            await channel.send(embed=embed, view=VoteView())
    except Exception as e:
        logging.error(f"Fehler beim Senden im Channel: {e}")

    # ================= REMINDER ============================

    when = datetime.fromtimestamp(next_vote_ts, timezone.utc)
    asyncio.create_task(funktion2(user_id, when))
    return None


# ============================================================
# =================== TOP.GG TEST EVENT ======================
# ============================================================

@bot.event
async def on_dbl_test(data):
    """
    Wird ausgelöst, wenn das Top.gg Webhook-System getestet wird
    """
    logging.info(f"on_dbl_test ausgelöst: {data!r}")

    guild = bot.get_guild(1141116981697859736)
    if guild is None:
        logging.error("Guild nicht gefunden")
        return

    channel = guild.get_channel(1361006871753789532)
    if channel is None:
        logging.error("Channel nicht gefunden")
        return

    user_id = int(data.get("user", 0))
    user = bot.get_user(user_id)
    user_display = f"{user}({user.id})" if user else f"Unbekannt ({user_id})"

    astra = bot.get_user(int(data.get("bot", bot.user.id)))

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


# ============================================================
# ================= COMMAND SAMMLER ==========================
# ============================================================

def all_app_commands(bot):
    """
    Gibt alle globalen und guild-spezifischen App Commands zurück
    (ohne Duplikate)
    """
    global_commands = bot.tree.get_commands()

    from itertools import chain
    guild_commands = chain.from_iterable(bot.tree._guild_commands.values())

    all_commands = list(global_commands) + list(guild_commands)

    seen = set()
    unique = []

    for cmd in all_commands:
        sig = (cmd.name, getattr(cmd, "type", None))
        if sig not in seen:
            seen.add(sig)
            unique.append(cmd)

    return unique


# ============================================================
# ======================== ON READY ==========================
# ============================================================

@bot.event
async def on_ready():
    """
    Wird ausgelöst, wenn der Bot vollständig bereit ist
    """
    servercount = len(bot.guilds)
    usercount = sum(guild.member_count for guild in bot.guilds)
    commandCount = len(all_app_commands(bot))
    channelCount = sum(len(guild.channels) for guild in bot.guilds)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:

            # Tabelle für Website-Stats anlegen
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS website_stats (
                    id INT PRIMARY KEY,
                    servercount INT,
                    usercount INT,
                    commandCount INT,
                    channelCount INT
                )
            """)

            # Prüfen ob Datensatz existiert
            await cur.execute("SELECT id FROM website_stats WHERE id=1")
            result = await cur.fetchone()

            if result is None:
                # Initialer Insert
                await cur.execute(
                    """
                    INSERT INTO website_stats
                    (id, servercount, usercount, commandCount, channelCount)
                    VALUES (1, %s, %s, %s, %s)
                    """,
                    (servercount, usercount, commandCount, channelCount)
                )
            else:
                # Update
                await cur.execute(
                    """
                    UPDATE website_stats
                    SET servercount=%s,
                        usercount=%s,
                        commandCount=%s,
                        channelCount=%s
                    WHERE id=1
                    """,
                    (servercount, usercount, commandCount, channelCount)
                )

            # Bot-Präsenz setzen
            await bot.change_presence(
                activity=discord.Game('Astra V2 out now! 💙'),
                status=discord.Status.online
            )

# ============================================================
# ===================== VOTE REMINDER ========================
# ============================================================

async def funktion2(user_id: int, when: datetime):
    """
    Reminder nach 12h:
    - prüft, ob Reminder noch gültig ist
    - sendet DM
    - entfernt ggf. die Voterole
    - verbraucht den Reminder in der DB
    """
    await bot.wait_until_ready()

    # UTC-Sicherheit
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    logging.info(f"[VoteReminder] task scheduled for {user_id} -> {when.isoformat()}")

    # Warten bis Zeitpunkt erreicht ist
    await discord.utils.sleep_until(when)

    now = datetime.now(timezone.utc)
    logging.info(f"[VoteReminder] task woke up for {user_id} at {now.isoformat()}")

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:

            # ================= GÜLTIGKEIT PRÜFEN =================

            try:
                await cur.execute(
                    "SELECT next_vote_epoch FROM topgg WHERE userID=%s",
                    (user_id,)
                )
                row = await cur.fetchone()
                current_ts = row[0] if row else None

                # Reminder bereits verbraucht
                if current_ts is None:
                    logging.info(f"[VoteReminder] skip {user_id} – already used")
                    return

                # Neuer Reminder existiert
                if current_ts > int(when.timestamp()):
                    logging.info(
                        f"[VoteReminder] skip {user_id} – newer reminder exists (ts={current_ts})"
                    )
                    return

            except Exception as e:
                logging.warning(
                    f"[VoteReminder] Vorab-Check fehlgeschlagen ({user_id}): {e}"
                )

            # ================= DM SENDEN =========================

            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)

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
                logging.info(f"[VoteReminder] DM erfolgreich an {user_id}")

            except Exception as e:
                logging.warning(
                    f"[VoteReminder] ❌ DM an {user_id} fehlgeschlagen: {e}"
                )

            # ================= ROLLE ENTFERNEN ===================

            guild = bot.get_guild(1141116981697859736)
            voterole = guild.get_role(1141116981756575875) if guild else None

            if guild and voterole:
                try:
                    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                except Exception:
                    member = None

                if member and voterole in getattr(member, "roles", []):
                    try:
                        await member.remove_roles(
                            voterole,
                            reason="Voterole Cooldown abgelaufen"
                        )
                        logging.info(f"[VoteReminder] Rolle entfernt bei {user_id}")
                    except Exception as e:
                        logging.warning(
                            f"[VoteReminder] Rolle entfernen fehlgeschlagen ({user_id}): {e}"
                        )

            # ================= REMINDER VERBRAUCHEN ==============

            try:
                await cur.execute(
                    """
                    UPDATE topgg
                    SET next_vote_epoch=NULL
                    WHERE userID=%s AND next_vote_epoch <= %s
                    """,
                    (user_id, int(when.timestamp()))
                )
            except Exception as e:
                logging.error(
                    f"[VoteReminder] DB-Update fehlgeschlagen ({user_id}): {e}"
                )

        try:
            await conn.commit()
        except Exception:
            pass

    logging.info("[VoteReminder] finished")

# ============================================================
# ===================== REMINDER TASK ========================
# ============================================================

async def funktion(when: datetime):
    """
    Führt normale Erinnerungen aus:
    - wartet bis Zeitpunkt
    - sendet DM
    - löscht Reminder aus DB
    """
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

                    embed = discord.Embed(
                        title="<:Astra_time:1141303932061233202> Erinnerung abgeschlossen.",
                        description=(
                            f"Hier ist deine Erinnerung\n"
                            f"<:Astra_arrow:1141303823600717885> {grund}"
                        ),
                        colour=discord.Colour.blue()
                    )

                await user.send(embed=embed)
                await cur.execute(
                    "DELETE FROM reminder WHERE grund = (%s)",
                    (grund,)
                )


# ============================================================
# ================== SLASH COMMAND GRUPPE ====================
# ============================================================

@app_commands.guild_only()
class Reminder(app_commands.Group):
    """
    Slash-Command Gruppe: /erinnerung
    """

    def __init__(self):
        super().__init__(
            name="erinnerung",
            description="Verwalte Erinnerungen."
        )

    # ========================================================
    # ================= REMINDER ERSTELLEN ===================
    # ========================================================

    @app_commands.command(
        name="erstellen",
        description="Setze eine Erinnerung."
    )
    @app_commands.describe(beschreibung="Beschreibung der Erinnerung.")
    @app_commands.describe(zeit="Wie lange bis zur Erinnerung.")
    async def reminder_set(
        self,
        interaction: discord.Interaction,
        beschreibung: str,
        zeit: Literal[
            '1m', '3m', '5m', '10m', '20m', '30m', '45m',
            '1h', '2h', '5h', '10h', '12h', '18h',
            '1d', '2d', '5d', '6d',
            '1w', '2w', '4w'
        ]
    ):
        """
        Erstellt eine neue Erinnerung
        """
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                description = beschreibung
                time = zeit

                await cur.execute(
                    "SELECT grund FROM reminder WHERE userID = (%s)",
                    (interaction.user.id,)
                )
                result = await cur.fetchall()

                # ================= ERSTE ERINNERUNG =================

                if result == ():
                    remindid = 1
                    time1 = convert(zeit)
                    t1 = math.floor(
                        discord.utils.utcnow().timestamp() + time1
                    )
                    t2 = datetime.fromtimestamp(
                        t1,
                        tz=timezone.utc
                    )

                    asyncio.create_task(funktion(t2))

                    await cur.execute(
                        """
                        INSERT INTO reminder(userID, grund, time, remindID)
                        VALUES(%s, %s, %s, %s)
                        """,
                        (interaction.user.id, description, t1, remindid)
                    )

                    embed = discord.Embed(
                        title=(
                            f"<:Astra_time:1141303932061233202> "
                            f"Erinnerung erstellt (ID {remindid})"
                        ),
                        description=(
                            f"Erinnerung gesetzt auf "
                            f"{discord.utils.format_dt(t2, 'F')}\n"
                            f"<:Astra_arrow:1141303823600717885> {description}"
                        ),
                        colour=discord.Colour.blue()
                    )

                    await interaction.response.send_message(embed=embed)

                # ================= WEITERE ERINNERUNGEN =============

                if result:
                    time1 = convert(zeit)
                    t1 = math.floor(
                        discord.utils.utcnow().timestamp() + time1
                    )
                    t2 = datetime.fromtimestamp(
                        t1,
                        tz=timezone.utc
                    )

                    asyncio.create_task(funktion(t2))

                    await cur.execute(
                        """
                        INSERT INTO reminder(userID, grund, time, remindID)
                        VALUES(%s, %s, %s, %s)
                        """,
                        (
                            interaction.user.id,
                            description,
                            t1,
                            len(result) + 1
                        )
                    )

                    embed = discord.Embed(
                        title=(
                            f"<:Astra_time:1141303932061233202> "
                            f"Erinnerung erstellt (ID {len(result) + 1})"
                        ),
                        description=(
                            f"Erinnerung gesetzt auf "
                            f"{discord.utils.format_dt(t2, 'F')}\n"
                            f"<:Astra_arrow:1141303823600717885> {description}"
                        ),
                        colour=discord.Colour.blue()
                    )

                    await interaction.response.send_message(embed=embed)

    # ========================================================
    # ================= REMINDER ANZEIGEN ====================
    # ========================================================

    @app_commands.command(
        name="anzeigen",
        description="Zeigt alle Erinnerungen an."
    )
    async def reminder_list(self, interaction: discord.Interaction):
        """
        Listet alle aktiven Erinnerungen auf
        """
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                member = interaction.user
                memberid = member.id

                await cur.execute(
                    "SELECT grund, remindID, time FROM reminder WHERE userID = (%s)",
                    (memberid,)
                )
                result = await cur.fetchall()

                if result == ():
                    embed2 = discord.Embed(
                        title=f"Alle Erinnerungen von {member}, {memberid}",
                        description=(
                            f"{member.name} hat zur Zeit "
                            f"keine aktiven Erinnerungen."
                        ),
                        color=discord.Color.blue()
                    )
                    await interaction.response.send_message(embed=embed2)

                else:
                    embed = discord.Embed(
                        title=f"Alle Erinnerungen von {member.name}, {memberid}",
                        description=(
                            "Um eine Erinnerung zu setzen, "
                            "nutze den Befehl `/erinnerung erstellen`."
                        ),
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow()
                    )

                    embed.set_author(
                        name=interaction.user,
                        icon_url=interaction.user.avatar
                    )

                    for eintrag in result:
                        reason = eintrag[0]
                        warnID = eintrag[1]
                        time = eintrag[2]

                        embed.add_field(
                            name=f"ID: {warnID}",
                            value=(
                                f"<:Astra_arrow:1141303823600717885>: {reason}\n"
                                f"<:Astra_time:1141303932061233202> "
                                f"Endet: <t:{time}:F>"
                            ),
                            inline=True
                        )

                    await interaction.response.send_message(embed=embed)

    # ========================================================
    # ================= REMINDER LÖSCHEN =====================
    # ========================================================

    @app_commands.command(
        name="löschen",
        description="Löscht eine Erinnerung."
    )
    @app_commands.describe(id="Die ID der Erinnerung.")
    async def reminder_delete(
        self,
        interaction: discord.Interaction,
        id: int
    ):
        """
        Löscht eine Erinnerung anhand der ID
        """
        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                member = interaction.user

                await cur.execute(
                    "SELECT remindID FROM reminder WHERE userID = (%s)",
                    (member.id,)
                )
                result = await cur.fetchall()

                if result:
                    await cur.execute(
                        """
                        DELETE FROM reminder
                        WHERE userID = (%s) AND remindID = (%s)
                        """,
                        (member.id, id)
                    )

                    embed2 = discord.Embed(
                        title="Erinnerung Gelöscht",
                        description=(
                            f"Die Erinnerung mit der ID ``{id}`` "
                            f"wurde gelöscht."
                        ),
                        color=discord.Color.green()
                    )
                    await interaction.response.send_message(embed=embed2)

                if not result:
                    embed2 = discord.Embed(
                        title="Keine Erinnerung gefunden",
                        description=(
                            f"Es gibt keine Aktive Erinnerung "
                            f"mit der ID: ``{id}``."
                        ),
                        color=discord.Color.green()
                    )
                    await interaction.response.send_message(embed=embed2)

# ============================================================
# ===================== OWNER COMMANDS =======================
# ============================================================

@bot.command()
@commands.guild_only()
@commands.is_owner()
async def advert(ctx):
    """
    Sendet eine Werbe-Nachricht für Astra
    """
    embed = discord.Embed(
        title="`🎃` Astra x Astra Support",
        url="https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands",
        description=(
            "Astra ist der einzige Bot, den Sie zur Verwaltung Ihres gesamten Servers benötigen. "
            "Es gibt viele Server, die Astra verwenden. Vielleicht sind Sie der Nächste?\n\n"
            "> __**Was bieten wir an?**__\n"
            "・<:Astra_ticket:1141833836204937347> Öffentliches Ticketsystem für Ihren Server\n"
            "・<:Astra_time:1141303932061233202> Automatische Moderation\n"
            "・<:Astra_messages:1141303867850641488> Willkommen/Nachrichten hinterlassen\n"
            "・<:Astra_settings:1141303908778639490> Joinrole&Botrole\n"
            "・<:Astra_herz:1141303857855594527> Reaktionsrollen\n"
            "・<:Astra_global1:1141303843993436200> Globalchat\n\n\n"
            "> __**Nützliche Links:**__\n"
            "・[Astra einladen ➚](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n"
            "・[Support erhalten ➚](https://discord.gg/eatdJPfjWc)"
        ),
        colour=discord.Colour.blue()
    )

    embed.set_image(
        url="https://cdn.discordapp.com/attachments/842039934142513152/879880068262940672/Astra-premium3.gif"
    )
    embed.set_thumbnail(url=ctx.guild.icon.url)

    msg = await ctx.send("https://discord.gg/eatdJPfjWc", embed=embed)
    await ctx.message.delete()


# ============================================================
# ===================== SYNC COMMAND =========================
# ============================================================

@bot.command()
@commands.is_owner()
async def sync(ctx, serverid: int = None):
    """
    Synchronisiert Slash-Commands
    """
    if serverid is None:
        try:
            s = await bot.tree.sync()
            a = 0
            for command in s:
                a += 1

            embed = discord.Embed(
                color=discord.Color.orange(),
                title="Synchronisierung",
                description=(
                    f"Die Synchronisierung von `{a} Commands` wurde eingeleitet.\n"
                    "Es wird ungefähr eine Stunde dauern, "
                    "damit sie global angezeigt werden."
                )
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                f"**❌ Synchronisierung fehlgeschlagen**\n```\n{e}```"
            )

    if serverid is not None:
        guild = bot.get_guild(int(serverid))

        if guild:
            try:
                s = await bot.tree.sync(
                    guild=discord.Object(id=guild.id)
                )
                a = 0
                for command in s:
                    a += 1

                embed = discord.Embed(
                    color=discord.Color.orange(),
                    title="Synchronisierung",
                    description=(
                        f"Die Synchronisierung von `{a} Commands` ist fertig.\n"
                        f"Es wird nur maximal eine Minute dauern, "
                        f"weil sie nur auf dem Server {guild.name} "
                        f"synchronisiert wurden."
                    )
                )
                await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(
                    f"**❌ Synchronisierung fehlgeschlagen**\n```\n{e}```"
                )

        if guild is None:
            await ctx.send(
                f"❌ Der Server mit der ID `{serverid}` wurde nicht gefunden."
            )


# ============================================================
# ======================= FLASK APP ==========================
# ============================================================

app = Flask(__name__)

@app.route('/status')
def status():
    """
    Status-Endpoint für externe Checks
    """
    return jsonify(online=True)


def run_flask():
    """
    Startet Flask mit Waitress (produktionsreif)
    """
    serve(app, host="localhost", port=5000)


# ============================================================
# ======================== START =============================
# ============================================================

if __name__ == "__main__":
    # Flask in separatem Thread starten
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    # Discord Bot starten
    bot.run(TOKEN)
