import discord
from waitress import serve
import threading
from discord.ext import commands
from flask import Flask, jsonify
import traceback
import asyncio
import topgg
import aiomysql
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import logging
from threading import Lock
from utils.db_scheme import run_sql_file
from utils.logger import setup_logging
from utils.presence import rotating_presence
from utils.file_watcher import Watcher
from events.topgg import setup_topgg_events
from utils.cleanup import cleanup_logs_task

guild_cache = {}
guild_cache_lock = Lock()
bot_ready = False

setup_logging()


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
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        intents.messages = True
        intents.message_content = True
        intents.reactions = True
        intents.presences = False

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
        self.is_connecting = False
        self.bot_ready = False
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
        self.automod_deleted_messages = set()

    async def setup_hook(self):
        try:
            # Task zum periodischen Leeren des Automod-Caches starten (Sicherheitsmaßnahme)
            self.loop.create_task(self.clear_automod_cache_task())

            # 1. Datenbank-Verbindung herstellen (Priorität hoch)
            await self.connect_db()
            await self.init_tables()

            # 2. Cogs laden
            await self.load_cogs()

            # 3. Externe Dienste (Top.gg)
            if dbl_token:
                self.topggpy = topgg.DBLClient(self, str(dbl_token))
            
            if dbl_password and dbl_port:
                try:
                    self.topgg_webhook = topgg.WebhookManager(self).dbl_webhook(
                        "/webhook/7d9f1c0a-topgg-astrabot", str(dbl_password)
                    )
                    await self.topgg_webhook.run(int(dbl_port))
                except Exception as e:
                    logging.error(f"❌ Fehler beim Starten des Top.gg Webhooks: {e}")

            # 4. Hintergrund-Tasks
            self.loop.create_task(rotating_presence(self))
            self.loop.create_task(cleanup_logs_task(self))
            self.keep_alive_task = self.loop.create_task(self.keep_db_alive())

            self.watcher = Watcher(self)
            self.watcher.start()

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
        except Exception:
            logging.exception("❌ Kritischer Fehler beim Setup")
            raise

    async def keep_db_alive(self):
        """Überprüft regelmäßig die MySQL-Verbindung und hält den DB-Pool funktionsfähig."""
        while not self.is_closed():
            try:
                if self.pool is None:
                    logging.warning("⚠️ DB-Pool ist nicht verfügbar. Warte 10 Sekunden...")
                    await asyncio.sleep(10)
                    continue

                async with self.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                        await cur.fetchone()

                logging.debug("💚 DB-Healthcheck erfolgreich")

            except asyncio.CancelledError:
                logging.info("🛑 DB-Healthcheck-Task wurde beendet.")
                raise

            except Exception as e:
                logging.error(
                    f"❌ DB-Healthcheck fehlgeschlagen: {type(e).__name__}: {e}",
                    exc_info=True
                )

                # Pool schließen und komplett neu aufbauen
                try:
                    if self.pool is not None:
                        self.pool.close()
                        await self.pool.wait_closed()
                        self.pool = None

                    logging.warning("🔄 Versuche, die DB-Verbindung neu aufzubauen...")
                    await asyncio.sleep(5)

                    await self.connect_db()
                    logging.info("✅ DB-Verbindung erfolgreich wiederhergestellt.")

                except asyncio.CancelledError:
                    raise

                except Exception as reconnect_error:
                    logging.error(
                        f"❌ Wiederherstellung der DB-Verbindung fehlgeschlagen: "
                        f"{type(reconnect_error).__name__}: {reconnect_error}",
                        exc_info=True
                    )

                    # Nicht sofort spammen/retryen
                    await asyncio.sleep(30)
                    continue

            await asyncio.sleep(120)

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
        """Initialisiert die Datenbank, führt einen Healthcheck aus und stellt offene Vote-Reminder wieder her."""

        try:
            # 1. SQL-Schema / Tabellen initialisieren
            await run_sql_file(self.pool)
            logging.info("✅ Datenbank-Tabellen erfolgreich initialisiert.")

            # 2. DB-Healthcheck
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    result = await cur.fetchone()

                    if not result or result[0] != 1:
                        raise RuntimeError("DB-Healthcheck lieferte kein gültiges Ergebnis.")

            logging.info("✅ DB-Test erfolgreich")
            logging.info("───────────────────── ✓ ─────────────────────")

            # 3. Bereits vorhandene Vote-Reminder aus der Datenbank laden
            if not self.task2:
                self.task2 = True

                async with self.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                                          SELECT userID, next_vote_epoch
                                          FROM topgg
                                          WHERE next_vote_epoch IS NOT NULL
                                          ORDER BY next_vote_epoch ASC
                                          """)

                        eintraege2 = await cur.fetchall()

                logging.info(
                    f"🔄 {len(eintraege2)} offene Vote-Reminder aus der Datenbank geladen."
                )

                async def starte_voterole_tasks():
                    erfolgreich = 0
                    übersprungen = 0
                    fehler = 0

                    now = datetime.now(timezone.utc)

                    for user_id, ts in eintraege2:
                        try:
                            if not ts:
                                übersprungen += 1
                                continue

                            when = datetime.fromtimestamp(int(ts), timezone.utc)

                            # Bereits fällige Reminder sofort ausführen
                            if when <= now:
                                when = now

                            asyncio.create_task(
                                self.funktion2(user_id, when)
                            )

                            erfolgreich += 1

                            # Nicht tausende Tasks gleichzeitig erzeugen
                            await asyncio.sleep(0.05)

                        except Exception:
                            fehler += 1
                            logging.exception(
                                f"❌ Reminder-Replay-Fehler "
                                f"(user={user_id}, ts={ts})"
                            )

                    logging.info(
                        f"✅ Vote-Reminder-Replay abgeschlossen: "
                        f"{erfolgreich} gestartet, "
                        f"{übersprungen} übersprungen, "
                        f"{fehler} Fehler."
                    )

                # Replay bewusst im Hintergrund starten,
                # damit der eigentliche Bot-Start nicht auf alle Reminder wartet.
                asyncio.create_task(starte_voterole_tasks())

            logging.info("")
            logging.info("")
            logging.info("──────────────── ⏱️ TASKS ────────────────")
            logging.info("✅ Tasks Registered!")
            logging.info("───────────────────── ✓ ────────────────────")

        except asyncio.CancelledError:
            logging.info("🛑 init_tables() wurde abgebrochen.")
            raise

        except Exception:
            logging.exception("❌ Kritischer Fehler bei der Datenbankinitialisierung.")
            raise

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

    async def clear_automod_cache_task(self):
        """Leert den Automod-Cache periodisch, um Speicherlecks zu vermeiden."""
        while not self.is_closed():
            await asyncio.sleep(3600)  # Einmal pro Stunde
            self.automod_deleted_messages.clear()

    async def on_message(self, msg):
        if msg.author.bot:
            return
        await self.process_commands(msg)

        if self.user is None:
            return

        botcreated_ts = int(self.user.created_at.timestamp())

        if msg.content in (f"<@{self.user.id}>", f"<@!{self.user.id}>"):
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
                text="Astra Development ©2025 • Mehr Infos auf unserem Support-Server.",
                icon_url=msg.guild.icon.url if msg.guild and msg.guild.icon else None,
            )

            await msg.channel.send(embed=embed)

    async def on_connect(self):
        self.is_connecting = True
        logging.info("🌐 Bot verbindet sich mit Discord...")

    async def on_resumed(self):
        self.is_connecting = False
        logging.info("♻️ WebSocket-Sitzung erfolgreich fortgesetzt.")

    async def on_ready(self):
        self.is_connecting = False
        if self.pool is None:
            return
        with guild_cache_lock:
            guild_cache.clear()
            for g in self.guilds:
                guild_cache[g.id] = g

        servercount = len(self.guilds)
        usercount = sum(guild.member_count or 0 for guild in self.guilds)
        commandCount = len(self.all_app_commands())
        channelCount = sum(len(guild.channels) for guild in self.guilds)

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Updaten oder Einfügen (UPSERT Simulation für MySQL)
                await cur.execute("""
                    INSERT INTO website_stats (id, servercount, usercount, commandCount, channelCount)
                    VALUES (1, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        servercount=%s, usercount=%s, commandCount=%s, channelCount=%s
                """, (servercount, usercount, commandCount, channelCount,
                      servercount, usercount, commandCount, channelCount))
                
                self.bot_ready = True

    def all_app_commands(self):
        global_commands = self.tree.get_commands()
        from itertools import chain

        guild_commands = chain.from_iterable(self.tree._guild_commands.values())
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

    async def funktion2(self, user_id: int, when: datetime):
        """Sendet einen Vote-Reminder, entfernt die Voterolle und verbraucht den Reminder sicher."""

        try:
            # ---------------------------------------------------------
            # 1. Warten, bis Discord vollständig bereit ist
            # ---------------------------------------------------------
            await self.wait_until_ready()

            # ---------------------------------------------------------
            # 2. Zeitpunkt UTC-sicher machen
            # ---------------------------------------------------------
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)

            reminder_ts = int(when.timestamp())

            # Bis zum eigentlichen Reminder warten
            await discord.utils.sleep_until(when)

            logging.info(
                f"[VoteReminder] ⏰ Reminder fällig für User {user_id} "
                f"(timestamp={reminder_ts})"
            )

            # ---------------------------------------------------------
            # 3. Prüfen, ob überhaupt ein DB-Pool vorhanden ist
            # ---------------------------------------------------------
            if self.pool is None:
                logging.error(
                    f"[VoteReminder] ❌ Kein DB-Pool verfügbar für User {user_id}. "
                    f"Reminder wird nicht verarbeitet."
                )
                return

            # ---------------------------------------------------------
            # 4. Prüfen, ob der Reminder noch gültig ist
            # ---------------------------------------------------------
            try:
                async with self.pool.acquire() as conn:
                    async with conn.cursor() as cur:

                        await cur.execute(
                            """
                            SELECT next_vote_epoch
                            FROM topgg
                            WHERE userID = %s
                            """,
                            (user_id,),
                        )

                        row = await cur.fetchone()

                        # Kein DB-Eintrag / Reminder wurde bereits entfernt
                        if not row:
                            logging.info(
                                f"[VoteReminder] ℹ️ Kein Eintrag für User {user_id}. "
                                f"Reminder wird übersprungen."
                            )
                            return

                        current_ts = row[0]

                        # Reminder wurde bereits verbraucht
                        if current_ts is None:
                            logging.info(
                                f"[VoteReminder] ℹ️ Reminder für User {user_id} "
                                f"wurde bereits verarbeitet."
                            )
                            return

                        # User hat inzwischen erneut gevotet.
                        # Dadurch wurde ein NEUER next_vote_epoch gesetzt.
                        if int(current_ts) > reminder_ts:
                            logging.info(
                                f"[VoteReminder] 🔄 Veralteter Reminder für User {user_id}. "
                                f"Alter={reminder_ts}, Neu={current_ts}"
                            )
                            return

            except asyncio.CancelledError:
                raise

            except Exception:
                logging.exception(
                    f"[VoteReminder] ❌ Vorab-Check der Datenbank fehlgeschlagen "
                    f"(user={user_id}). Reminder wird sicherheitshalber abgebrochen."
                )
                return

            # ---------------------------------------------------------
            # 5. DM senden
            # ---------------------------------------------------------
            try:
                user = self.get_user(user_id)

                if user is None:
                    user = await self.fetch_user(user_id)

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

                logging.info(
                    f"[VoteReminder] 📩 DM erfolgreich an User {user_id} gesendet."
                )

            except asyncio.CancelledError:
                raise

            except discord.Forbidden:
                logging.warning(
                    f"[VoteReminder] ⚠️ DM an User {user_id} nicht möglich "
                    f"(DMs deaktiviert / blockiert)."
                )

            except discord.NotFound:
                logging.warning(
                    f"[VoteReminder] ⚠️ User {user_id} wurde nicht gefunden."
                )

            except Exception:
                logging.exception(
                    f"[VoteReminder] ❌ Unerwarteter Fehler beim Senden der DM "
                    f"(user={user_id})."
                )

            # ---------------------------------------------------------
            # 6. Voterolle entfernen
            # ---------------------------------------------------------
            guild = self.get_guild(1141116981697859736)

            if guild is None:
                logging.warning(
                    f"[VoteReminder] ⚠️ Support-Guild nicht im Cache "
                    f"(user={user_id})."
                )

            else:
                voterole = guild.get_role(1141116981756575875)

                if voterole is None:
                    logging.warning(
                        f"[VoteReminder] ⚠️ Voterole nicht gefunden "
                        f"(user={user_id})."
                    )

                else:
                    try:
                        member = guild.get_member(user_id)

                        if member is None:
                            member = await guild.fetch_member(user_id)

                        if member is None:
                            logging.info(
                                f"[VoteReminder] ℹ️ User {user_id} ist nicht "
                                f"mehr auf dem Support-Server."
                            )

                        elif voterole in member.roles:
                            await member.remove_roles(
                                voterole,
                                reason="Voterole Cooldown abgelaufen",
                            )

                            logging.info(
                                f"[VoteReminder] 🏷️ Voterole von User {user_id} entfernt."
                            )

                        else:
                            logging.debug(
                                f"[VoteReminder] ℹ️ User {user_id} hatte die "
                                f"Voterole bereits nicht mehr."
                            )

                    except asyncio.CancelledError:
                        raise

                    except discord.NotFound:
                        logging.info(
                            f"[VoteReminder] ℹ️ User {user_id} ist nicht mehr "
                            f"auf dem Support-Server."
                        )

                    except discord.Forbidden:
                        logging.error(
                            f"[VoteReminder] ❌ Keine Berechtigung, die Voterole "
                            f"von User {user_id} zu entfernen."
                        )

                    except Exception:
                        logging.exception(
                            f"[VoteReminder] ❌ Fehler beim Entfernen der Voterole "
                            f"(user={user_id})."
                        )

            # ---------------------------------------------------------
            # 7. Reminder in der DB verbrauchen
            #
            # WICHTIG:
            # Die Bedingung next_vote_epoch <= reminder_ts verhindert,
            # dass ein neuer Vote versehentlich gelöscht wird.
            # ---------------------------------------------------------
            if self.pool is None:
                logging.error(
                    f"[VoteReminder] ❌ DB-Pool nach Verarbeitung nicht verfügbar "
                    f"(user={user_id}). Reminder konnte nicht gelöscht werden."
                )
                return

            try:
                async with self.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE topgg
                            SET next_vote_epoch = NULL
                            WHERE userID = %s
                              AND next_vote_epoch <= %s
                            """,
                            (user_id, reminder_ts),
                        )

                        updated_rows = cur.rowcount

                    await conn.commit()

                if updated_rows > 0:
                    logging.info(
                        f"[VoteReminder] ✅ Reminder erfolgreich abgeschlossen "
                        f"(user={user_id})."
                    )
                else:
                    logging.info(
                        f"[VoteReminder] ℹ️ Reminder für User {user_id} "
                        f"war bereits geändert/verbraucht."
                    )

            except asyncio.CancelledError:
                raise

            except Exception:
                logging.exception(
                    f"[VoteReminder] ❌ DB-Update zum Verbrauch des Reminders "
                    f"fehlgeschlagen (user={user_id})."
                )

        except asyncio.CancelledError:
            # Task wurde absichtlich beendet → NICHT als Fehler behandeln
            raise

        except Exception:
            # Letzte Sicherheitsstufe:
            # Kein unerwarteter Fehler darf den Task unbemerkt sterben lassen.
            logging.exception(
                f"[VoteReminder] 💥 Unerwarteter Fehler in funktion2 "
                f"(user={user_id})."
            )


bot = Astra()


setup_topgg_events(bot)



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
    if not bot.bot_ready:
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
    if not bot.bot_ready:
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
