import os
import time
import asyncio
import logging
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger("watcher")


class ReloadHandler(FileSystemEventHandler):
    def __init__(self, bot):
        self.bot = bot
        self.last_event = {}
        self.cooldown = 1.5
        self.file_cache = {}
        self.lock = threading.Lock()
        self.restart_in_progress = False
        self.start_time = time.time()
        self.grace_period = 10.0  # Sekunden, in denen beim Start nichts passiert

    def has_changed(self, path):
        try:
            mtime = os.path.getmtime(path)
            with self.lock:
                if self.file_cache.get(path) == mtime:
                    return False
                self.file_cache[path] = mtime
            return True
        except Exception:
            return False

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".py"):
            return

        now = time.time()
        if now - self.start_time < self.grace_period:
            return

        path = event.src_path.replace("\\", "/")

        with self.lock:
            last = self.last_event.get(path, 0)
            if now - last < self.cooldown:
                return
            self.last_event[path] = now

        # ❌ utils komplett ignorieren
        if "/utils/" in path:
            return

        # ❌ events komplett ignorieren
        if "/events/" in path:
            return

        if not self.has_changed(path):
            return

        # 🔥 MAIN → Restart (asynchron via Thread, um Watcher nicht zu blockieren)
        if path.endswith("main.py"):
            with self.lock:
                if self.restart_in_progress:
                    return
                self.restart_in_progress = True

            # Check Bot Status: Kein Restart während Verbindung oder Initialisierung
            is_connecting = getattr(self.bot, "is_connecting", False)
            is_ready = self.bot.is_ready()

            if is_connecting or not is_ready:
                logger.warning(f"Restart unterdrückt (Bot verbindet/nicht bereit). is_connecting: {is_connecting}, is_ready: {is_ready}")
                with self.lock:
                    self.restart_in_progress = False
                return

            logger.warning(f"Main geändert: {path} → Restart in 2s geplant...")
            def delayed_restart():
                time.sleep(2.0)
                try:
                    logger.warning("Führe System-Restart aus...")
                    if os.name == "nt":  # Windows
                        logger.info("Restart auf Windows: Bitte den Bot manuell neu starten oder ein Process-Manager nutzen.")
                    else:  # Linux/Unix
                        os.system("/usr/bin/systemctl restart astrabot.service")
                except Exception as e:
                    logger.error(f"Fehler beim Restart: {e}")
                finally:
                    with self.lock:
                        self.restart_in_progress = False

            threading.Thread(target=delayed_restart, daemon=True).start()
            return

        # 🔥 COG → Reload
        if "/cogs/" in path:
            try:
                # Kein Cog-Reload während Verbindung
                if getattr(self.bot, "is_connecting", False):
                    logger.warning(f"Reload für {path} unterdrückt (Bot verbindet sich gerade).")
                    return

                rel_path = path.split("/cogs/")[1]
                parts = rel_path.split("/")
                cog_name = "cogs." + ".".join(p.replace(".py", "") for p in parts)

                logger.info(f"Cog Änderung erkannt: {cog_name}")
                if self.bot.loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.safe_reload(cog_name),
                        self.bot.loop
                    )
                else:
                    logger.warning(f"Bot-Loop läuft nicht. Überspringe Reload für {cog_name}")
            except Exception as e:
                logger.error(f"Fehler beim Extrahieren des Cog-Namens aus {path}: {e}")

    async def safe_reload(self, cog_name):
        try:
            # Kurze Pause, um sicherzustellen, dass die Datei fertig geschrieben ist
            await asyncio.sleep(0.5)
            await self.bot.reload_extension(cog_name)
            logger.info(f"✅ Reloaded: {cog_name}")
        except Exception as e:
            try:
                await self.bot.load_extension(cog_name)
                logger.info(f"✅ Loaded: {cog_name}")
            except Exception as e2:
                logger.error(f"❌ Fehler beim Laden/Reloaden von {cog_name}: {e}")


class Watcher:
    def __init__(self, bot):
        self.bot = bot
        self.observer = Observer()
        self.handler = ReloadHandler(bot)

    def start(self):
        self.observer.schedule(self.handler, path=".", recursive=True)
        self.observer.start()
        logger.info("Watcher gestartet")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        logger.info("Watcher gestoppt")