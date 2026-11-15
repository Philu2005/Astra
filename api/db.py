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
        self._started = False  # True nur, wenn Thread/Loop läuft UND Pool vorhanden ist
        self._lock = threading.Lock()
        # Start-Signalisierung
        self._start_ok_event: Optional[threading.Event] = None
        self._start_fail_event: Optional[threading.Event] = None

    # ---- öffentliche API ----
    def start(self) -> None:
        # Mehrfachstart vermeiden, aber auch fehlerhafte Vorstarts zurücksetzen
        with self._lock:
            # Wenn bereits erfolgreich gestartet und Thread lebt -> nichts tun
            if self._started and self._thread is not None and self._thread.is_alive():
                return

            # .env vom VPS (falls vorhanden) laden, ohne bestehende Variablen zu überschreiben
            try:
                load_dotenv("/root/Astra/.env", override=False)
            except Exception:
                # Nicht kritisch im lokalen/test Umfeld
                pass

            # Events pro Startdurchlauf neu anlegen
            self._start_ok_event = threading.Event()
            self._start_fail_event = threading.Event()

            # Event-Loop in separatem Thread aufbauen
            self._thread = threading.Thread(target=self._thread_main, name="astra-api-db-loop", daemon=True)
            self._thread.start()

        # Auf erstes Ergebnis der Initialisierung warten (ohne dauerhaft zu blockieren)
        # 10 Sekunden sind ausreichend, um Netzwerkfehler/Fehlkonfig zu erkennen.
        ok_event = self._start_ok_event
        fail_event = self._start_fail_event
        if ok_event is None or fail_event is None:
            return

        signaled = ok_event.wait(timeout=10) or fail_event.wait(timeout=0)
        if not signaled:
            # Keine Entscheidung innerhalb des Timeouts – Thread könnte weiter initialisieren.
            # In diesem Fall markieren wir nicht als gestartet, bis der OK-Event gesetzt wird.
            return

        # Wenn Fehlerereignis gesetzt wurde, sicherstellen, dass als nicht gestartet gilt
        if fail_event.is_set():
            with self._lock:
                self._started = False
            return
        # Erfolgreich initialisiert
        with self._lock:
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
            self._start_ok_event = None
            self._start_fail_event = None

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

    def is_ready(self) -> bool:
        return self._pool is not None and self._loop is not None and not self._loop.is_closed()

    # ---- interner Thread/Loop ----
    def _thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            # Versuch: Pool initialisieren
            success = loop.run_until_complete(self._init_pool())
            if success:
                # Erfolg signalisieren
                if self._start_ok_event is not None:
                    self._start_ok_event.set()
                loop.run_forever()
            else:
                # Fehlstart signalisieren und Loop beenden
                if self._start_fail_event is not None:
                    self._start_fail_event.set()
                return
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
                try:
                    loop.close()
                finally:
                    # Sicherstellen, dass Status zurückgesetzt wird
                    with self._lock:
                        self._started = False
                        self._loop = None
                        self._thread = None

    async def _init_pool(self):
        import aiomysql  # lokale Importzeit im Loop

        # Konfiguration aus Umgebungsvariablen (keine geheimen Fallbacks erfinden)
        host = os.getenv("ASTRA_API_DB_HOST")
        port_str = os.getenv("ASTRA_API_DB_PORT")
        user = os.getenv("ASTRA_API_DB_USER")
        password = os.getenv("ASTRA_API_DB_PASSWORD")
        db = os.getenv("ASTRA_API_DB_NAME")

        minsize_str = os.getenv("ASTRA_API_DB_MIN_SIZE", "1")
        maxsize_str = os.getenv("ASTRA_API_DB_MAX_SIZE", "10")

        # Validierung der Pflichtparameter
        missing = [
            name for name, val in (
                ("ASTRA_API_DB_HOST", host),
                ("ASTRA_API_DB_PORT", port_str),
                ("ASTRA_API_DB_USER", user),
                ("ASTRA_API_DB_PASSWORD", password),
                ("ASTRA_API_DB_NAME", db),
            ) if not val
        ]
        if missing:
            logger.error(
                "DB-Konfiguration unvollständig: fehlende Variablen: %s",
                ", ".join(missing),
            )
            self._pool = None
            return False

        # Typ-/Bereichsprüfungen
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError("port out of range")
        except Exception:
            logger.error("Ungültiger ASTRA_API_DB_PORT: %r", port_str)
            self._pool = None
            return False

        try:
            minsize = int(minsize_str)
            maxsize = int(maxsize_str)
            if minsize < 1 or maxsize < 1 or minsize > maxsize:
                raise ValueError("invalid pool size range")
        except Exception:
            logger.error("Ungültige Pool-Größen: min=%r max=%r", minsize_str, maxsize_str)
            self._pool = None
            return False

        # Pool erstellen; keine Credentials loggen
        try:
            self._pool = await aiomysql.create_pool(
                host=host,
                port=port,
                user=user,
                password=password,
                db=db,
                autocommit=True,
                minsize=minsize,
                maxsize=maxsize,
                charset="utf8mb4",
            )
            logger.info("Astra API DB-Pool initialisiert")
            return True
        except Exception as e:
            # Aussagekräftiges, aber sicheres Logging inkl. Stacktrace
            safe_msg = str(e).splitlines()[0][:500]
            logger.exception(
                "Astra API DB-Pool konnte nicht initialisiert werden (%s): %s",
                type(e).__name__,
                safe_msg,
            )
            # Pool bleibt None – Aufrufer behandeln 503
            self._pool = None
            return False


# Singleton-Instanz
api_db = _ApiDBManager()


# Beim Prozessende automatisch stoppen
atexit.register(api_db.stop)
