import discord
from discord.ext import commands
import traceback
import asyncio
import topgg
import aiomysql
import aiohttp
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import logging
from threading import Lock
from utils.db_scheme import run_sql_file
from utils.logger import setup_logging
from utils.presence import rotating_presence
from utils.file_watcher import Watcher
from utils.cleanup import cleanup_logs_task
from utils.branding import get_current_colour
from utils.branding import start_branding_task
from events.topgg import setup_topgg_events
from events.topgg_webhook import start_topgg_webhook

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
dbl_secret_new = os.getenv("DBL_SECRET_NEW")
internal_api_key = (os.getenv("ASTRA_INTERNAL_API_KEY") or "").strip()
internal_api_base_url = (os.getenv("ASTRA_INTERNAL_API_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
bot_heartbeat_url = internal_api_base_url + "/heartbeat"
bot_guild_sync_url = internal_api_base_url + "/guild-sync"
bot_heartbeat_interval = max(5, int(os.getenv("ASTRA_HEARTBEAT_INTERVAL_SECONDS", "30")))
bot_sync_retries = max(1, int(os.getenv("ASTRA_GUILD_SYNC_RETRIES", "3")))
bot_snapshot_sync_interval = max(30, int(os.getenv("ASTRA_GUILD_SNAPSHOT_INTERVAL_SECONDS", "60")))



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

        self.topggpy = None
        self.topgg_webhook_runner = None

        self.task = False
        self.task2 = False
        self.watcher = None
        self.pool = None
        self.is_connecting = False
        self.bot_ready = False
        self.branding_task = None
        self.heartbeat_task = None
        self.guild_snapshot_task = None
        self.guild_sync_lock = asyncio.Lock()
        self.command_count_lock = asyncio.Lock()
        self.command_count = 0

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
            # Automod-Cache regelmäßig leeren
            self.loop.create_task(self.clear_automod_cache_task())

            # 1. Datenbank verbinden
            await self.connect_db()
            await self.init_tables()

            # 2. Cogs laden
            await self.load_cogs()

            # 3. Top.gg einrichten
            if dbl_token:
                self.topggpy = topgg.DBLClient(self, str(dbl_token))

            if dbl_secret_new and dbl_port:
                self.topgg_webhook_runner = await start_topgg_webhook(
                    self,
                    str(dbl_secret_new),
                    int(dbl_port)
                )

                logging.info("[Top.gg] Neuer Webhook erfolgreich gestartet.")

            else:
                logging.warning(
                    "[Top.gg] Webhook nicht gestartet. "
                    "DBL_SECRET_NEW oder DBL_PORT fehlt."
                )

            # 4. Hintergrund-Tasks
            self.branding_task = start_branding_task(self)

            self.loop.create_task(rotating_presence(self))
            self.loop.create_task(cleanup_logs_task(self))

            self.keep_alive_task = self.loop.create_task(
                self.keep_db_alive()
            )

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

    async def close(self):
        try:
            if self.guild_snapshot_task is not None:
                self.guild_snapshot_task.cancel()
                try:
                    await self.guild_snapshot_task
                except asyncio.CancelledError:
                    pass
                self.guild_snapshot_task = None

            if self.topgg_webhook_runner is not None:
                await self.topgg_webhook_runner.cleanup()
                self.topgg_webhook_runner = None

                logging.info("[Top.gg] Webhook wurde beendet.")

        finally:
            await super().close()


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
            try:
                await asyncio.sleep(3600)  # Einmal pro Stunde
                self.automod_deleted_messages.clear()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.exception(f"[AutomodCache] Fehler im clear_automod_cache_task: {e}")

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
                colour=get_current_colour(),
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

    async def on_disconnect(self):
        self.is_connecting = True
        logging.warning("⚠️ Verbindung zum Discord-Gateway unterbrochen.")

    async def on_ready(self):
        self.is_connecting = False
        if self.pool is None:
            return
        with guild_cache_lock:
            guild_cache.clear()
            for g in self.guilds:
                guild_cache[g.id] = g

        await self._ensure_website_stats_row()
        await self._load_command_count()

        servercount = len(self.guilds)
        usercount = sum(guild.member_count or 0 for guild in self.guilds)
        commandCount = self.command_count
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

        if self.heartbeat_task is None or self.heartbeat_task.done():
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        if self.guild_snapshot_task is None or self.guild_snapshot_task.done():
            self.guild_snapshot_task = asyncio.create_task(self._guild_snapshot_loop())

        asyncio.create_task(self._sync_full_guild_snapshot())

    async def _ensure_website_stats_row(self):
        if self.pool is None:
            return
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT IGNORE INTO website_stats (id, servercount, usercount, commandCount, channelCount)
                    VALUES (1, 0, 0, 0, 0)
                """)

    async def _load_command_count(self):
        if self.pool is None:
            return
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT commandCount FROM website_stats WHERE id = 1 LIMIT 1")
                row = await cur.fetchone()
                value = 0
                if row and row[0] is not None:
                    try:
                        value = int(row[0])
                    except (TypeError, ValueError):
                        value = 0
                self.command_count = max(0, value)

    def _build_global_stats(self) -> dict:
        return {
            "users": int(sum(guild.member_count or 0 for guild in self.guilds)),
            "guilds": int(len(self.guilds)),
            "commands": int(self.command_count),
        }

    async def _serialize_guild_for_sync(self, guild: discord.Guild) -> dict:
        channels = []
        for channel in getattr(guild, "channels", []):
            channels.append({
                "id": str(channel.id),
                "name": str(channel.name),
                "type": str(channel.type),
            })

        roles = []
        for role in getattr(guild, "roles", []):
            perms = getattr(role, "permissions", None)
            roles.append({
                "id": str(role.id),
                "name": str(role.name),
                "permissions": {
                    "administrator": bool(getattr(perms, "administrator", False)),
                    "manage_guild": bool(getattr(perms, "manage_guild", False)),
                },
            })

        members = []
        for member in getattr(guild, "members", []):
            perms = getattr(member, "guild_permissions", None)
            members.append({
                "id": str(member.id),
                "permissions": {
                    "administrator": bool(getattr(perms, "administrator", False)),
                    "manage_guild": bool(getattr(perms, "manage_guild", False)),
                },
            })

        return {
            "id": str(guild.id),
            "name": str(guild.name),
            "owner_id": str(guild.owner_id),
            "icon": guild.icon.key if guild.icon else None,
            "member_count": guild.member_count,
            "channels": channels,
            "roles": roles,
            "members": members,
        }

    async def _post_internal_api(self, payload: dict) -> bool:
        if not internal_api_key:
            return False

        headers = {"Authorization": f"Bearer {internal_api_key}"}
        timeout = aiohttp.ClientTimeout(total=10)
        for attempt in range(1, bot_sync_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(bot_guild_sync_url, json=payload, headers=headers) as response:
                        if response.status < 400:
                            return True
                        logging.warning("[GuildSync] API antwortete mit HTTP %s (Versuch %s/%s).", response.status, attempt, bot_sync_retries)
            except Exception as e:
                logging.warning("[GuildSync] API nicht erreichbar (Versuch %s/%s): %s", attempt, bot_sync_retries, e)

            if attempt < bot_sync_retries:
                await asyncio.sleep(min(5, attempt))

        return False

    async def _sync_full_guild_snapshot(self):
        async with self.guild_sync_lock:
            try:
                guilds = [await self._serialize_guild_for_sync(guild) for guild in self.guilds]
                payload = {
                    "mode": "full_snapshot",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "stats": self._build_global_stats(),
                    "guilds": guilds,
                }
                await self._post_internal_api(payload)
            except Exception:
                logging.exception("[GuildSync] Fehler bei vollständiger Guild-Synchronisation.")

    async def _guild_snapshot_loop(self):
        while not self.is_closed():
            try:
                await self._sync_full_guild_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("[GuildSync] Fehler im Snapshot-Loop.")
            await asyncio.sleep(bot_snapshot_sync_interval)

    async def on_guild_join(self, guild: discord.Guild):
        return

    async def on_guild_remove(self, guild: discord.Guild):
        return

    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        return

    async def on_member_join(self, member: discord.Member):
        return

    async def on_member_remove(self, member: discord.Member):
        return

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        return

    async def on_guild_role_create(self, role: discord.Role):
        return

    async def on_guild_role_delete(self, role: discord.Role):
        return

    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        return

    async def on_guild_channel_create(self, channel):
        return

    async def on_guild_channel_delete(self, channel):
        return

    async def on_guild_channel_update(self, before, after):
        return

    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        if interaction.user and interaction.user.bot:
            return
        if self.pool is None:
            return
        async with self.command_count_lock:
            self.command_count += 1
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        UPDATE website_stats
                        SET commandCount = commandCount + 1
                        WHERE id = 1
                    """)

    async def _send_heartbeat(self):
        if not internal_api_key:
            return

        ws = getattr(self, "ws", None)
        gateway_connected = bool(ws is not None and not self.is_closed() and not self.is_connecting)
        payload = {
            "gateway_connected": gateway_connected,
            "is_ready": bool(self.is_ready()),
            "is_connecting": bool(self.is_connecting),
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }

        shard_count = getattr(self, "shard_count", None)
        if shard_count:
            payload["shards"] = [
                {"id": shard_id, "latency": round(latency, 4)}
                for shard_id, latency in self.latencies
            ]

        timeout = aiohttp.ClientTimeout(total=10)
        headers = {"Authorization": f"Bearer {internal_api_key}"}

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(bot_heartbeat_url, json=payload, headers=headers) as response:
                    if response.status >= 400:
                        logging.warning("[Heartbeat] API antwortete mit HTTP %s.", response.status)
        except Exception as e:
            logging.warning("[Heartbeat] API nicht erreichbar: %s", e)

    async def _heartbeat_loop(self):
        while not self.is_closed():
            await self._send_heartbeat()
            await asyncio.sleep(bot_heartbeat_interval)

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
                    colour=get_current_colour(),
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


if __name__ == "__main__":
    bot.run(TOKEN)
