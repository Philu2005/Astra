import asyncio
from typing import Any


# Prozessweiter, optional gesetzter Verweis auf die laufende Bot‑Instanz.
_bot_instance: Any | None = None


def set_bot_instance(bot: Any) -> None:
    """Wird vom Bot-Prozess (main.py) aufgerufen, um die laufende Instanz zu registrieren.

    Dieses Modul importiert KEINE Bot- oder Discord-Abhängigkeiten und kann daher
    gefahrlos von der internen API verwendet werden, ohne main.py zu laden.
    """
    global _bot_instance
    _bot_instance = bot


def get_bot_instance() -> Any | None:
    """Gibt die aktuell registrierte Bot-Instanz zurück (oder None, falls keine läuft)."""
    return _bot_instance


def submit_bot_task(coro, timeout: float | None = None):
    """Reicht eine Coroutine sicher im Event-Loop der registrierten Bot-Instanz ein.

    - Verwendet asyncio.run_coroutine_threadsafe, um aus Fremd-Threads auf den Bot-Loop
      zuzugreifen.
    - Beibehaltung des bisherigen Timeout-Verhaltens.
    """
    bot = get_bot_instance()
    if bot is None or getattr(bot, "is_closed", lambda: True)():
        raise RuntimeError("Bot not available")
    loop = getattr(bot, "loop", None)
    if loop is None:
        raise RuntimeError("Bot event loop not available")
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)
