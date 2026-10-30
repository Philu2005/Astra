from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Union
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("Astra.Branding")

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# utils/branding.py -> Projektstamm
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILBILDER_DIR = PROJECT_ROOT / "cogs" / "assets" / "Profilbilder"
STATE_FILE = PROJECT_ROOT / ".astra_branding_state.json"
BRANDING_GUILD_ID = 1141116981697859736


class BrandingEvent(str, Enum):
    EASTER = "ostern"
    HALLOWEEN = "halloween"
    CHRISTMAS = "weihnachten"
    STANDARD = "standard"


@dataclass(frozen=True)
class BrandingInfo:
    event: BrandingEvent
    name: str
    colour: discord.Colour
    avatar_filename: str
    avatar_path: Path


# Eine zentrale Konfiguration für Events, Farben und Bilddateien.
BRANDING_CONFIGS: dict[BrandingEvent, dict[str, object]] = {
    BrandingEvent.STANDARD: {
        "name": "Standard",
        "colour": discord.Colour.blue(),
        "filename": "Idee_2_blau.jpg",
    },
    BrandingEvent.HALLOWEEN: {
        "name": "Halloween",
        "colour": discord.Colour.orange(),
        "filename": "Astra_halloween.jpg",
    },
    BrandingEvent.EASTER: {
        "name": "Ostern",
        "colour": discord.Colour.green(),
        "filename": "Astra_ostern.jpg",
    },
    BrandingEvent.CHRISTMAS: {
        "name": "Weihnachten",
        "colour": discord.Colour.red(),
        "filename": "Astra_weihnachten.jpg",
    },
}


def calculate_easter_sunday(year: int) -> date:
    """Berechnet Ostersonntag im gregorianischen Kalender."""
    if year < 1583:
        raise ValueError("Die Osterberechnung erwartet ein Jahr ab 1583.")

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_easter_range(year: int) -> tuple[date, date]:
    """Liefert Karfreitag und Ostermontag für das angegebene Jahr."""
    easter_sunday = calculate_easter_sunday(year)
    return easter_sunday - timedelta(days=2), easter_sunday + timedelta(days=1)


def _to_berlin_date(value: Optional[Union[datetime, date]] = None) -> date:
    """Wandelt einen Zeitpunkt in das Datum von Europe/Berlin um."""
    if value is None:
        return datetime.now(BERLIN_TZ).date()

    # datetime ist eine Unterklasse von date, deshalb zuerst prüfen.
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Naive Datetimes werden ausdrücklich als Berliner Ortszeit interpretiert.
            return value.date()
        return value.astimezone(BERLIN_TZ).date()

    if isinstance(value, date):
        return value

    raise TypeError("value muss datetime, date oder None sein.")


def _get_branding_info(event: BrandingEvent) -> BrandingInfo:
    config = BRANDING_CONFIGS[event]
    filename = str(config["filename"])
    return BrandingInfo(
        event=event,
        name=str(config["name"]),
        colour=config["colour"],  # type: ignore[arg-type]
        avatar_filename=filename,
        avatar_path=PROFILBILDER_DIR / filename,
    )


def get_current_branding(
    dt: Optional[Union[datetime, date]] = None,
) -> BrandingInfo:
    """Ermittelt das aktive Branding nach Berliner Kalenderdatum."""
    check_date = _to_berlin_date(dt)
    year = check_date.year

    # Priorität: Ostern, Halloween, Weihnachten, Standard.
    easter_start, easter_end = get_easter_range(year)
    if easter_start <= check_date <= easter_end:
        return _get_branding_info(BrandingEvent.EASTER)

    if date(year, 10, 25) <= check_date <= date(year, 10, 31):
        return _get_branding_info(BrandingEvent.HALLOWEEN)

    if date(year, 12, 24) <= check_date <= date(year, 12, 26):
        return _get_branding_info(BrandingEvent.CHRISTMAS)

    return _get_branding_info(BrandingEvent.STANDARD)


def get_current_colour(
    dt: Optional[Union[datetime, date]] = None,
) -> discord.Colour:
    """Liefert die zum aktuellen Datum passende Branding-Farbe."""
    return get_current_branding(dt).colour


def get_current_avatar_path(
    dt: Optional[Union[datetime, date]] = None,
) -> Path:
    """Liefert den absoluten Pfad zum passenden Profilbild."""
    return get_current_branding(dt).avatar_path


def _read_saved_event() -> Optional[BrandingEvent]:
    """Liest das zuletzt erfolgreich gesetzte Event aus der lokalen Statusdatei."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return BrandingEvent(data["event"])
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        logger.warning(
            "[Branding] Statusdatei fehlt oder ist ungültig; "
            "das Avatar-Branding wird erneut abgeglichen."
        )
        return None


def _save_event(event: BrandingEvent) -> None:
    """Speichert das zuletzt erfolgreich gesetzte Event atomar."""
    temporary_file = STATE_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps({"event": event.value}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_file.replace(STATE_FILE)


_last_applied_event: Optional[BrandingEvent] = _read_saved_event()
_branding_task: Optional[tasks.Loop] = None
_task_bot_id: Optional[int] = None


async def update_avatar(
    bot: commands.Bot,
    force: bool = False,
) -> bool:
    """
    Aktualisiert das Bot-Profilbild bei Bedarf.

    True bedeutet, dass ein Avatar-Update erfolgreich durchgeführt wurde.
    False bedeutet, dass kein Update nötig war oder es nicht durchgeführt werden konnte.
    """
    global _last_applied_event

    branding = get_current_branding()
    event = branding.event

    if not bot.is_ready() or bot.user is None:
        logger.debug("[Branding] Bot ist noch nicht bereit; Avatar-Update übersprungen.")
        return False

    # Nach einem Neustart verhindert die Statusdatei unnötige Uploads.
    # force=True erzwingt bewusst einen erneuten Upload.
    if not force and _last_applied_event == event:
        logger.debug(
            "[Branding] Das zuletzt gesetzte Branding ist bereits '%s'.",
            branding.name,
        )
        return False

    avatar_path = branding.avatar_path
    if not avatar_path.is_file():
        logger.error("[Branding] Profilbilddatei nicht gefunden: %s", avatar_path)
        return False

    try:
        avatar_bytes = avatar_path.read_bytes()
        if not avatar_bytes:
            logger.error("[Branding] Profilbilddatei ist leer: %s", avatar_path)
            return False

        logger.info(
            "[Branding] Setze Profilbild auf '%s' (%s).",
            branding.name,
            avatar_path.name,
        )
        await bot.user.edit(avatar=avatar_bytes)

        # Server-Avatar (Icon) des Zielservers ebenfalls anpassen
        guild = bot.get_guild(BRANDING_GUILD_ID)
        if guild is None:
            try:
                guild = await bot.fetch_guild(BRANDING_GUILD_ID)
            except (discord.HTTPException, discord.NotFound):
                logger.warning(
                    "[Branding] Server %s nicht gefunden; Server-Avatar wird nicht aktualisiert.",
                    BRANDING_GUILD_ID,
                )

        if guild is not None:
            try:
                logger.info(
                    "[Branding] Setze Server-Avatar für Server %s auf '%s' (%s).",
                    BRANDING_GUILD_ID,
                    branding.name,
                    avatar_path.name,
                )
                await guild.edit(icon=avatar_bytes)
                logger.info(
                    "[Branding] Server-Avatar für Server %s erfolgreich auf '%s' gesetzt.",
                    BRANDING_GUILD_ID,
                    branding.name,
                )
            except discord.Forbidden:
                logger.warning(
                    "[Branding] Fehlende Berechtigungen zum Ändern des Server-Avatars für Server %s.",
                    BRANDING_GUILD_ID,
                )
            except discord.HTTPException:
                logger.exception(
                    "[Branding] Discord-API-Fehler beim Ändern des Server-Avatars für Server %s.",
                    BRANDING_GUILD_ID,
                )

        # Erst nach erfolgreicher Discord-Änderung den Status speichern.
        _save_event(event)
        _last_applied_event = event
        logger.info("[Branding] Profilbild erfolgreich auf '%s' gesetzt.", branding.name)
        return True

    except discord.HTTPException:
        logger.exception("[Branding] Discord-API-Fehler beim Avatarwechsel.")
    except OSError:
        logger.exception("[Branding] Datei-/Dateisystemfehler beim Avatarwechsel.")
    except Exception:
        logger.exception("[Branding] Unerwarteter Fehler beim Avatarwechsel.")

    return False


def start_branding_task(bot: commands.Bot) -> tasks.Loop:
    """Startet den stündlichen Branding-Task höchstens einmal pro Bot-Instanz."""
    global _branding_task, _task_bot_id

    bot_id = id(bot)
    if _branding_task is not None and _branding_task.is_running():
        if _task_bot_id == bot_id:
            logger.debug("[Branding] Branding-Task läuft bereits.")
            return _branding_task

        raise RuntimeError(
            "Der Branding-Task läuft bereits für eine andere Bot-Instanz. "
            "Beende zuerst den bestehenden Task."
        )

    @tasks.loop(time=datetime_time(hour=0, minute=0, tzinfo=BERLIN_TZ), reconnect=True)
    async def branding_loop() -> None:
        await update_avatar(bot)

    @branding_loop.before_loop
    async def before_branding_loop() -> None:
        await bot.wait_until_ready()
        logger.info("[Branding] Bot bereit; die erste Prüfung startet jetzt.")

    @branding_loop.error
    async def branding_loop_error(error: BaseException) -> None:
        logger.error(
            "[Branding] Unerwarteter Fehler im Hintergrundtask.",
            exc_info=(type(error), error, error.__traceback__),
        )

    _branding_task = branding_loop
    _task_bot_id = bot_id
    branding_loop.start()
    logger.info("[Branding] Saisonales Branding gestartet (tägliche Prüfung um 00:00 Uhr Europe/Berlin).")
    return branding_loop


def stop_branding_task() -> None:
    """Beendet den Branding-Task, falls er läuft."""
    global _branding_task, _task_bot_id

    if _branding_task is not None and _branding_task.is_running():
        _branding_task.cancel()
        logger.info("[Branding] Branding-Task wurde beendet.")

    _branding_task = None
    _task_bot_id = None
