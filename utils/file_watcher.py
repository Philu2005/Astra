import os
import time
import asyncio
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger("watcher")


class ReloadHandler(FileSystemEventHandler):
    def __init__(self, bot):
        self.bot = bot
        self.last_event = {}
        self.cooldown = 1.5
        self.file_cache = {}

    def has_changed(self, path):
        try:
            mtime = os.path.getmtime(path)
            if self.file_cache.get(path) == mtime:
                return False
            self.file_cache[path] = mtime
            return True
        except Exception:
            return False

    def on_modified(self, event):
        if not event.src_path.endswith(".py"):
            return

        now = time.time()
        path = event.src_path.replace("\\", "/")

        last = self.last_event.get(path, 0)

        if now - last < self.cooldown:
            return

        # ❌ utils komplett ignorieren
        if "/utils/" in path:
            return

        if not self.has_changed(path):
            return

        self.last_event[path] = now

        # 🔥 MAIN → Restart
        if path.endswith("main.py"):
            logger.warning("Main geändert → Restart via systemd")
            os.system("systemctl restart astrabot.service")

        # 🔥 COG → Reload
        if "/cogs/" in path:
            rel_path = path.split("/cogs/")[1]
            parts = rel_path.split("/")

            cog_name = "cogs." + ".".join(p.replace(".py", "") for p in parts)

            asyncio.run_coroutine_threadsafe(
                self.safe_reload(cog_name),
                self.bot.loop
            )

    async def safe_reload(self, cog_name):
        try:
            await self.bot.reload_extension(cog_name)
            logger.info(f"Reloaded: {cog_name}")
        except Exception:
            try:
                await self.bot.load_extension(cog_name)
                logger.info(f"Loaded: {cog_name}")
            except Exception as e:
                logger.error(f"{cog_name}: {e}")


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