import os
import threading
import asyncio
import atexit
import logging
from typing import Optional, Any

from dotenv import load_dotenv

logger = logging.getLogger("astra.api.db")


class _ApiDBManager:
    """Verwaltet einen eigenen aiomysql-Pool und einen dedizierten Event-Loop-Thread
    für die Astra Internal API, vollständig unabhängig vom Discord‑Bot.

    Nutzung:
      - api_db.start() beim API-Start aufrufen (idempotent)
      - api_db.run_coro(coro, timeout=None) zum Ausführen von DB‑Coroutines
      - api_db.get_pool() für direkten Poolzugriff in Coroutines
      - api_db.stop() beim Shutdown (automatisch via atexit)
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._pool = None
        self._started = False
        self._lock = threading.Lock()

    # ---- öffentliche API ----
    def start(self) -> None:
        with self._lock:
            if self._started:
                return

            # .env vom VPS (falls vorhanden) laden, ohne bestehende Variablen zu überschreiben
            try:
                load_dotenv("/root/Astra/.env", override=False)
            except Exception:
                # Nicht kritisch im lokalen/test Umfeld
                pass

            # Event-Loop in separatem Thread aufbauen
            self._thread = threading.Thread(target=self._thread_main, name="astra-api-db-loop", daemon=True)
            self._thread.start()
            self._started = True

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            pool = self._pool
            thread = self._thread
            self._started = False
            self._loop = None
            self._thread = None
            self._pool = None

        if loop is None:
            return

        async def _shutdown():
            try:
                if pool is not None:
                    pool.close()
                    await pool.wait_closed()
            except Exception as e:
                logger.warning(f"DB pool close failed: {e}")

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if thread is not None:
            try:
                thread.join(timeout=5)
            except Exception:
                pass

    def run_coro(self, coro, timeout: Optional[float] = None) -> Any:
        """Führt eine Coroutine im Hintergrund-Loop aus und liefert deren Ergebnis.
        Raises TimeoutError kompatibel bei Zeitüberschreitung.
        """
        loop = self._loop
        if loop is None or (hasattr(loop, "is_closed") and loop.is_closed()):
            raise RuntimeError("DB event loop not available")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    def get_pool(self):
        return self._pool

    # ---- interner Thread/Loop ----
    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._init_pool())
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop=loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                loop.close()

    async def _init_pool(self):
        import aiomysql  # lokale Importzeit im Loop

        # Konfiguration aus Umgebungsvariablen
        host = os.getenv("ASTRA_API_DB_HOST", "127.0.0.1")
        port = int(os.getenv("ASTRA_API_DB_PORT", "3306"))
        user = os.getenv("ASTRA_API_DB_USER", "astra_api")
        password = os.getenv("ASTRA_API_DB_PASSWORD", "")
        db = os.getenv("ASTRA_API_DB_NAME", "AstraDB")

        # Pool erstellen; keine Credentials loggen
        try:
            self._pool = await aiomysql.create_pool(
                host=host,
                port=port,
                user=user,
                password=password,
                db=db,
                autocommit=True,
                minsize=int(os.getenv("ASTRA_API_DB_MIN_SIZE", "1")),
                maxsize=int(os.getenv("ASTRA_API_DB_MAX_SIZE", "10")),
                charset="utf8mb4",
            )
            logger.info("Astra API DB-Pool initialisiert")
        except Exception as e:
            logger.error(f"Astra API DB-Pool konnte nicht initialisiert werden: {type(e).__name__}")
            # Pool bleibt None; Aufrufer behandeln 503


# Singleton-Instanz
api_db = _ApiDBManager()


# Beim Prozessende automatisch stoppen
atexit.register(api_db.stop)
