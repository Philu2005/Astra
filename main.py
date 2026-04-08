import discord
from waitress import serve
import threading
from discord.ext import commands
from discord import app_commands
from flask import Flask, jsonify
import math
import traceback
import asyncio
import topgg
import aiomysql
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import Literal
import re
import logging
from threading import Lock
from utils.db_scheme import run_sql_file
from utils.logger import setup_logging
from utils.presence import rotating_presence
from utils.file_watcher import Watcher
from events.topgg import setup_topgg_events

guild_cache = {}
guild_cache_lock = Lock()
bot_ready = False

setup_logging()

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.message_content = True
intents.reactions = True

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
host = os.getenv("DB_HOST")
benutzer = os.getenv("DB_USER")
password_db = os.getenv("DB_PASS")
db_name = os.getenv("DB_NAME")
dbl_token = os.getenv("DBL_TOKEN")
dbl_password = os.getenv("DBL_PASS")
dbl_port = os.getenv("DBL_PORT")


class Astra(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="astra!",
            help_command=None,
            case_insensitive=True,
            intents=intents,
        )

        pool: aiomysql.Pool
        self.topggpy = None
        self.task = False
        self.task2 = False
        self.watcher = None
        self.pool = None  # Pool-Objekt hier zentral gespeichert
        self.initial_extensions = [
            "cogs.reminder",
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
            "cogs.autorole",
            "cogs.reactionrole",
            "cogs.welcome",
            "cogs.leave",
            "cogs.modlog",
            "cogs.autoreact",
            "cogs.warns",
            "cogs.guessthenumber",
            "cogs.counting",
            "cogs.tags",
            "cogs.ticket",
            "cogs.levels",
            "cogs.snake",
        ]

    async def setup_hook(self):
        try:
            self.loop.create_task(rotating_presence(self))
            self.topggpy = topgg.DBLClient(self, str(dbl_token))
            bot.topgg_webhook = topgg.WebhookManager(bot).dbl_webhook(
                "/webhook/7d9f1c0a-topgg-astrabot", str(dbl_password)
            )
            await bot.topgg_webhook.run(int(dbl_port))
            await self.connect_db()
            await self.init_tables()
            await self.load_cogs()

            logging.info("")
            logging.info("")
            logging.info("──────────────── 🚀 STARTUP ────────────────")
            logging.info("Astra ist online!")
            logging.info("")
            logging.info(" █████╗ ███████╗████████╗██████╗  █████╗  ")
            logging.info("██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔══██╗ ")
            logging.info("███████║███████╗   ██║   ██████╔╝███████║ ")
            logging.info("██╔══██║╚════██║   ██║   ██╔══██╗██╔══██║ ")
            logging.info("██║  ██║███████║   ██║   ██║  ██║██║  ██║ ")
            logging.info("╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ")
            logging.info("───────────────────── ✓ ─────────────────────")
            self.watcher = Watcher(self)
            self.watcher.start()
            self.keep_alive_task = self.loop.create_task(self.keep_db_alive())
        except Exception as e:
            logging.error(f"❌ Fehler beim Setup:\n{e}")

    async def keep_db_alive(self):
        while True:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT 1"
                    )  # Einfacher Testbefehl, um die Verbindung aufrechtzuerhalten
            await asyncio.sleep(120)  # Alle 2 Minuten

    async def connect_db(self):
        """Stellt den DB-Pool her und speichert ihn in self.pool"""
        self.pool = await aiomysql.create_pool(  # type: ignore
            host=host,
            port=3306,
            user=benutzer,
            password=password_db,
            db=db_name,
            autocommit=True,
            pool_recycle=3600,
            connect_timeout=5,
            maxsize=50,
        )
        logging.info("")
        logging.info("")
        logging.info("──────────────── 🗄️ DATABASE ────────────────")
        logging.info("✅ DB-Verbindung erfolgreich")

    async def init_tables(self):
        """Erstellt/Registriert Tasks und führt einen DB-Healthcheck aus."""
        await run_sql_file(self.pool)

        # DB-Healthcheck
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        logging.info("✅ DB-Test erfolgreich")
        logging.info("───────────────────── ✓ ─────────────────────")

        # Aiomysql anstoßen
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:

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

        logging.info("")
        logging.info("")
        logging.info("──────────────── ⏱️ TASKS ────────────────")
        logging.info("✅ Tasks Registered!")
        logging.info("──────────────────── ✓ ────────────────────")

    async def load_cogs(self):
        """Lädt alle Cogs"""
        geladen, fehler = 0, 0

        # Optional: jishaku laden, aber Fehler ignorieren
        try:
            await self.load_extension("jishaku")
            logging.info("")
            logging.info("")
            logging.info("──────────────── 📦 COGS ────────────────")
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
                logging.error(f"❌ Fehler beim Laden von: {ext}")
                traceback.print_exc()
                logging.info("---------------------------------------------")

        gesamt = geladen + fehler
        logging.info(f"📦 Cogs geladen: {geladen}/{gesamt} erfolgreich ✅")
        logging.info("──────────────────── ✓ ────────────────────")
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
                ),
            )

            embed.set_author(
                name=str(msg.author),
                icon_url=msg.author.avatar.url if msg.author.avatar else None,
            )
            if msg.guild and msg.guild.icon:
                embed.set_thumbnail(url=msg.guild.icon.url)
            embed.set_footer(
                text="Astra Development ©2025 • Mehr Infos auf unserem Support-Server",
                icon_url=msg.guild.icon.url if msg.guild and msg.guild.icon else None,
            )

            await msg.channel.send(embed=embed)

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
                                if any(
                                    word in match.lower()
                                    for word in [
                                        "du",
                                        "bitte",
                                        "nicht",
                                        "kannst",
                                        "coin",
                                        "rolle",
                                        "hilfe",
                                        "server",
                                    ]
                                ):
                                    translatable.append(match)

        # main.py separat prüfen
        main_py_path = os.path.join(path, "main.py")
        if os.path.isfile(main_py_path):
            with open(main_py_path, "r", encoding="utf-8") as f:
                content = f.read()
                matches = string_regex.findall(content)
                for match in matches:
                    if any(
                        word in match.lower()
                        for word in [
                            "du",
                            "bitte",
                            "nicht",
                            "kannst",
                            "coin",
                            "rolle",
                            "hilfe",
                            "server",
                        ]
                    ):
                        translatable.append(match)

        return translatable


bot = Astra()


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
    if bot.pool is None:
        return
    with guild_cache_lock:
        guild_cache.clear()
        for g in bot.guilds:
            guild_cache[g.id] = g

    servercount = len(bot.guilds)
    usercount = sum(guild.member_count for guild in bot.guilds)
    commandCount = len(all_app_commands(bot))
    channelCount = sum(len(guild.channels) for guild in bot.guilds)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Tabelle erstellen, falls sie noch nicht existiert

            # Prüfen, ob Zeile mit id=1 existiert
            await cur.execute("SELECT id FROM website_stats WHERE id=1")
            result = await cur.fetchone()

            if result is None:
                # Wenn nicht, initialen Datensatz anlegen
                await cur.execute(
                    "INSERT INTO website_stats (id, servercount, usercount, commandCount, channelCount) VALUES (1, %s, %s, %s, %s)",
                    (servercount, usercount, commandCount, channelCount),
                )
            else:
                # Ansonsten updaten
                await cur.execute(
                    "UPDATE website_stats SET servercount=%s, usercount=%s, commandCount=%s, channelCount=%s WHERE id=1",
                    (servercount, usercount, commandCount, channelCount),
                )
            global bot_ready
            bot_ready = True


async def funktion2(user_id: int, when: datetime):
    await bot.wait_until_ready()

    # UTC-sicher
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    await discord.utils.sleep_until(when)
    now = datetime.now(timezone.utc)

    async with bot.pool.acquire() as conn:
        async with conn.cursor() as cur:
            # --- Schutz: ist der Reminder noch gültig? ---
            # Falls der User inzwischen erneut gevotet hat und ein NEUER next_vote_epoch gesetzt wurde,
            # ist dieser Task veraltet und wird übersprungen.
            try:
                await cur.execute(
                    "SELECT next_vote_epoch FROM topgg WHERE userID=%s", (user_id,)
                )
                row = await cur.fetchone()
                current_ts = row[0] if row else None
                if current_ts is None:
                    return
                if current_ts > int(when.timestamp()):
                    return
            except Exception as e:
                logging.warning(
                    f"[VoteReminder] Vorab-Check fehlgeschlagen ({user_id}): {e}"
                )

            # --- DM senden ---
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                embed = discord.Embed(
                    title="<:Astra_time:1141303932061233202> Du kannst wieder voten!",
                    url="https://top.gg/de/bot/1113403511045107773/vote",
                    description=(
                        "Der Cooldown von 12h ist vorbei. Es wäre schön, wenn du wieder votest.\n"
                        "Als Belohnung erhältst du eine spezielle Rolle auf unserem Support-Server."
                    ),
                    colour=discord.Colour.blue(),
                )
                await user.send(embed=embed)
            except Exception as e:
                logging.warning(
                    f"[VoteReminder] ❌ DM an {user_id} fehlgeschlagen: {e}"
                )

            # --- Rolle entfernen (optional) ---
            guild = bot.get_guild(1141116981697859736)
            voterole = guild.get_role(1141116981756575875) if guild else None
            if guild and voterole:
                try:
                    member = guild.get_member(user_id) or await guild.fetch_member(
                        user_id
                    )
                except Exception:
                    member = None
                if member and voterole in getattr(member, "roles", []):
                    try:
                        await member.remove_roles(
                            voterole, reason="Voterole Cooldown abgelaufen"
                        )
                    except Exception as e:
                        logging.warning(
                            f"[VoteReminder] Rolle entfernen fehlgeschlagen ({user_id}): {e}"
                        )

            # --- Reminder verbrauchen (nur wenn noch derselbe fällig ist) ---
            try:
                await cur.execute(
                    "UPDATE topgg SET next_vote_epoch=NULL "
                    "WHERE userID=%s AND next_vote_epoch <= %s",
                    (user_id, int(when.timestamp())),
                )
            except Exception as e:
                logging.error(
                    f"[VoteReminder] DB-Update fehlgeschlagen ({user_id}): {e}"
                )

        try:
            await conn.commit()
        except Exception:
            pass


bot.funktion2 = funktion2

setup_topgg_events(bot)


@bot.command()
@commands.guild_only()
@commands.is_owner()
async def advert(ctx):
    embed = discord.Embed(
        title="`🎃` Astra x Astra Support",
        url="https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands",
        description="Astra ist der einzige Bot, den Sie zur Verwaltung Ihres gesamten Servers benötigen. Es gibt viele Server, die Astra verwenden. Vielleicht sind Sie der Nächste?\n\n> __**Was bieten wir an?**__\n・<:Astra_ticket:1141833836204937347> Öffentliches Ticketsystem für Ihren Server\n・<:Astra_time:1141303932061233202> Automatische Moderation\n・<:Astra_messages:1141303867850641488> Willkommen/Nachrichten hinterlassen\n・<:Astra_settings:1141303908778639490> Joinrole&Botrole\n・<:Astra_herz:1141303857855594527> Reaktionsrollen\n・<:Astra_global1:1141303843993436200> Globalchat\n\n\n> __**Nützliche Links:**__\n・[Astra einladen ➚](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands)\n・[Support erhalten ➚](https://discord.gg/eatdJPfjWc)",
        colour=discord.Colour.blue(),
    )
    embed.set_image(
        url="https://cdn.discordapp.com/attachments/842039934142513152/879880068262940672/Astra-premium3.gif"
    )
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
            globalembed = discord.Embed(
                color=discord.Color.orange(),
                title="Synchronisierung",
                description=f"Die Synchronisierung von `{a} Commands` wurde eingeleitet.\nEs wird ungefähr eine Stunde dauern, damit sie global angezeigt werden.",
            )
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
                localembed = discord.Embed(
                    color=discord.Color.orange(),
                    title="Synchronisierung",
                    description=f"Die Synchronisierung von `{a} Commands` ist fertig.\nEs wird nur maximal eine Minute dauern, weil sie nur auf dem Server {guild.name} synchronisiert wurden.",
                )
                await ctx.send(embed=localembed)
            except Exception as e:
                await ctx.send(f"**❌ Synchronisierung fehlgeschlagen**\n```\n{e}```")
        if guild is None:
            await ctx.send(
                f"❌ Der Server mit der ID `{serverid}` wurde nicht gefunden."
            )


def serialize_guild(guild: discord.Guild):
    return {
        "id": str(guild.id).strip(),
        "name": guild.name,
        "icon": guild.icon.key if guild.icon else None,
        "memberCount": guild.member_count,
    }


app = Flask(__name__)


@app.route("/status")
def status():
    return jsonify(online=True)


@app.route("/servers")
def servers():
    if not bot.is_ready():
        return jsonify(success=False, error="Bot not ready"), 503

    with guild_cache_lock:
        servers = [serialize_guild(g) for g in guild_cache.values()]

    return jsonify(success=True, count=len(servers), servers=servers)


@app.route("/servers/<int:guild_id>")
def server_detail(guild_id):
    if not bot_ready:
        return jsonify(success=False, error="Bot not ready"), 503
    with guild_cache_lock:
        guild = guild_cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    return jsonify(
        success=True,
        server={
            "id": str(guild.id),
            "name": guild.name,
            "icon": guild.icon.key if guild.icon else None,
            "memberCount": guild.member_count,
            "channelCount": len(guild.channels),
            "roleCount": len(guild.roles),
            "ownerId": str(guild.owner_id),
        },
    )


@app.route("/servers/<int:guild_id>/roles")
def server_roles(guild_id):
    if not bot_ready:
        return jsonify(success=False, error="Bot not ready"), 503

    with guild_cache_lock:
        guild = guild_cache.get(guild_id)

    if not guild:
        return jsonify(success=False, error="Server not found"), 404

    roles = [
        {"id": str(role.id), "name": role.name}
        for role in guild.roles
        if role.name != "@everyone"
    ]

    return jsonify(success=True, count=len(roles), roles=roles)


def run_flask():
    serve(app, host="localhost", port=5000)  # produktionsreif, keine Warning


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
