# cogs/errors.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal
from utils.logging import setup_logging
import traceback, json, os, re, asyncio, aiohttp, tempfile, sys, platform
from pathlib import Path
from datetime import datetime, timezone


setup_logging()

PROJECT_ROOT = "/root/Astra"
LOG_CHANNEL_ID = 1141116983815962819

def _safe(o):
    try:
        return str(o)
    except Exception:
        return repr(o)


def _shorten_path(p: str) -> str:
    try:
        return str(Path(p).resolve()).replace(PROJECT_ROOT + "/", "")
    except Exception:
        return p

def _build_smart_tips(exc: BaseException, *, origin: str, code_line: str | None, short_exc: str) -> list[str]:
    msg = f"{type(exc).__name__}: {str(exc)}"
    tips: list[str] = []

    # ---- Generische Python-Fehler ----
    if isinstance(exc, AttributeError):
        if "NoneType" in msg:
            tips.append("Du greifst auf ein Objekt zu, das `None` ist. Prüfe vorher `if obj is not None:` oder nutze "
                        "sichere Properties wie `user.display_avatar.url` statt `user.avatar.url`.")
        else:
            tips.append("Attribut existiert nicht. Tippfehler? Oder falscher Objekttyp? Mit `dir(obj)` prüfen.")
    if isinstance(exc, KeyError):
        m = re.search(r"KeyError: '?(.*?)'?$", msg)
        k = f"`{m.group(1)}` " if m else ""
        tips.append(f"Dict-Schlüssel {k}fehlt. Vorher `if key in d:` prüfen oder `dict.get(key)` mit Default nutzen.")
    if isinstance(exc, TypeError):
        tips.append("Falsche Typen/Argumente. Signatur der Funktion prüfen und Parameterreihenfolge/Default-Werte checken.")
    if isinstance(exc, ValueError):
        if "invalid literal for int()" in msg:
            tips.append("String → int fehlgeschlagen. Vorher mit `.isdigit()` prüfen oder `try/except` umwandeln.")
        else:
            tips.append("Ungültiger Wert. Vor Übergabe validieren; ggf. klare Fehlermeldung werfen.")
    if isinstance(exc, ZeroDivisionError):
        tips.append("Division durch 0. Nenner vorab prüfen (`if x:`) oder `max(x, 1)`/Fehlerfälle abfangen.")
    if isinstance(exc, AssertionError):
        tips.append("Assertion schlug fehl. Prüfe die Annahmen in Tests/Guards oder ersetze `assert` durch sauberes Error-Handling.")

    # ---- Async/Netzwerk ----
    if isinstance(exc, asyncio.TimeoutError):
        tips.append("Timeout. Timeout-Wert erhöhen oder Operation beschleunigen; ggf. Retry mit Backoff einbauen.")
    if isinstance(exc, aiohttp.ClientConnectorError):
        tips.append("Konnte keine Verbindung aufbauen. DNS/Host, Firewall, Proxy und Internet-Zugang prüfen.")
    if isinstance(exc, aiohttp.ClientResponseError):
        tips.append(f"HTTP-Status {exc.status}. URL/Parameter/Token prüfen. Bei 401/403: Credentials/Rechte; bei 404: Endpoint/ID; "
                    "bei 5xx: später erneut versuchen / Retry mit Backoff.")

    # ---- Discord spezifisch ----
    if isinstance(exc, discord.Forbidden):
        tips.append("Discord `Forbidden`: Dem Bot fehlen Berechtigungen (z. B. Nachrichten senden, Webhooks verwalten, Rollen erwähnen). "
                    "Rollenhierarchie/Channel-Overrides prüfen.")
    if isinstance(exc, discord.NotFound):
        tips.append("Discord `NotFound`: Objekt existiert nicht (gelöschte Nachricht/Kanal/Webhook?). IDs/Cache neu laden.")
    if isinstance(exc, discord.HTTPException):
        if getattr(exc, "status", None) == 429 or "429" in msg:
            tips.append("Rate-Limit (429). Weniger häufig senden, Requests bündeln oder Backoff/Retry einbauen.")
        else:
            tips.append("Allgemeiner Discord HTTP-Fehler. Payload/Größenlimits (Embeds, Dateien) und Rechte prüfen.")

    # ---- MySQL / MariaDB (optional) ----
    try:
        import pymysql
        if isinstance(exc, (pymysql.err.IntegrityError, pymysql.err.OperationalError, pymysql.err.ProgrammingError)):
            if "1062" in msg or "Duplicate entry" in msg:
                tips.append("MySQL 1062 Duplicate Key: PRIMARY/UNIQUE-Key verletzt. Vorher prüfen oder "
                            "`INSERT ... ON DUPLICATE KEY UPDATE` nutzen.")
            if "1052" in msg and "ambiguous" in msg.lower():
                tips.append("MySQL 1052 Ambiguous Column: Spalten qualifizieren oder `VALUES()` / Aliase sauber nutzen.")
            if "1146" in msg or "doesn't exist" in msg:
                tips.append("Tabelle existiert nicht. Migration/CREATE TABLE ausführen und DB-User-Rechte prüfen.")
            if "1054" in msg and "Unknown column" in msg:
                tips.append("Spalte existiert nicht. Migration (`ALTER TABLE ... ADD COLUMN ...`) oder Code anpassen.")
            if "1045" in msg:
                tips.append("MySQL 1045 Access denied: Benutzer/Passwort/Host prüfen; Rechte (GRANT) setzen.")
            if "1049" in msg:
                tips.append("MySQL 1049 Unknown database: DB-Name in der Config prüfen oder DB anlegen.")
    except Exception:
        pass

    if "Invalid client credentials" in msg:
        tips.append("OAuth-Credentials invalid: `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET` prüfen oder Secret rotieren.")
    if "quota" in msg.lower() and "youtube" in msg.lower():
        tips.append("YouTube-Quota erreicht. API-Schlüssel prüfen, Abfragen drosseln, ggf. RSS nutzen (`YOUTUBE_USE_RSS=True`).")

    if code_line:
        tips.append(f"Zeile prüfen: `{code_line}`")

    if origin.endswith("notifier.py") and ("ambiguous" in msg.lower() or "Duplicate" in msg):
        tips.append("In `notifier.py` SQL-Query prüfen: Alias/`VALUES()`-Nutzung für Kompatibilität.")

    if not tips:
        tips.append("Fehler reproduzieren, `traceback.txt` checken und die Origin-Stelle untersuchen.")
    return tips


class ErrorCog(commands.Cog, name="errors"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # WICHTIG: KEIN self.bot.tree.on_error hier setzen → sonst Doppel-Antworten!

    @app_commands.command(name="testfehler",
                          description="Wirft absichtlich einen Fehler zum Testen des Error-Handlers.")
    async def testfehler(
            self,
            interaction: discord.Interaction,
            art: Literal["runtime", "zero", "nested"] = "runtime",
    ):
        try:

            if art == "runtime":
                raise RuntimeError("Absichtlich ausgelöster Testfehler (runtime).")

            elif art == "zero":
                1 / 0

            elif art == "nested":
                def a():
                    def b():
                        raise ValueError("Absichtlich verschachtelt (nested).")

                    b()

                a()

        except Exception as e:
            # 🔥 DAS IST DER WICHTIGE TEIL
            logging.error("❌ TEST ERROR:\n%s", traceback.format_exc())

            # Fehler weiterwerfen → damit dein ErrorCog ihn auch verarbeitet
            raise e

    # Einziger Handler: greift für alle App-Commands dieser Cog
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        await self._handle_error(interaction, error)

    async def _handle_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # User-Embed (ephemeral) – genau wie bei dir
        user_embed = discord.Embed(
            title="Unbekannter Fehler",
            description="❌ Ein unerwarteter Fehler ist aufgetreten. Der Fehler wurde geloggt!",
            colour=discord.Colour.red()
        )
        try:
            user_embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        except Exception:
            user_embed.set_author(name=str(interaction.user))

        # Kontext sammeln
        exc = error.original if isinstance(error, app_commands.CommandInvokeError) and getattr(error, "original", None) else error
        try:
            full_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        except Exception:
            full_trace = f"{type(exc).__name__}: {exc}"

        tb_list = traceback.extract_tb(getattr(exc, "__traceback__", None)) or []
        origin = "unbekannt"; code_line = None
        project_frames = [f for f in tb_list if str(f.filename).startswith(PROJECT_ROOT)]
        chosen = project_frames[-1] if project_frames else (tb_list[-1] if tb_list else None)
        if chosen:
            origin = f"{_shorten_path(chosen.filename)}:{chosen.lineno} in {chosen.name}()"
            code_line = (chosen.line or "").strip()

        short_exc = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        tips = _build_smart_tips(exc, origin=origin, code_line=code_line, short_exc=short_exc)

        # Optionen/Namespace → JSON für Log
        try:
            ns = getattr(interaction, "namespace", None)
            options = {k: v for k, v in (getattr(ns, "__dict__", {}) or {}).items()}
        except Exception:
            options = {}

        context = {
            "user": {"id": getattr(interaction.user, "id", None), "name": str(interaction.user)},
            "guild": {"id": getattr(interaction.guild, "id", None), "name": getattr(interaction.guild, "name", None)} if interaction.guild else None,
            "channel": {"id": getattr(interaction.channel, "id", None), "name": getattr(interaction.channel, "name", None)} if interaction.channel else None,
            "command": getattr(interaction.command, "name", None),
            "options": options,
            "bot": {
                "latency": round(self.bot.latency or 0, 3),
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "discord_py": discord.__version__,
                "os": f"{platform.system()} {platform.release()} | {platform.version()}",
                "pid": os.getpid(),
                "time": datetime.now(timezone.utc).isoformat()
            }
        }

        # Log-Embed im gewünschten Format
        log_embed = discord.Embed(
            title="SlashCommand Error",
            colour=discord.Colour.red(),
            timestamp=datetime.now(timezone.utc),
        )
        # User
        log_embed.add_field(
            name="User",
            value=f"{context['user']['name']} ({context['user']['id']})",
            inline=False
        )
        # Guild / Channel
        g = context["guild"]; c = context["channel"]
        log_embed.add_field(
            name="Guild / Channel",
            value=f"{g['name']} ({g['id']}) / # {c['name']} ({c['id']})" if g and c else "DM / unbekannt",
            inline=False
        )
        # Command + Options
        log_embed.add_field(name="Command", value=str(context["command"]), inline=False)
        log_embed.add_field(name="Options", value=f"```json\n{json.dumps(context['options'], ensure_ascii=False, indent=2)}\n```", inline=False)
        # Ort
        log_embed.add_field(name="Ort", value=origin, inline=False)
        # Fehler
        log_embed.add_field(name="Fehler", value=f"```{short_exc}```", inline=False)
        # Tipps
        if tips:
            log_embed.add_field(name="Tipps", value="\n".join(f"• {t}" for t in tips), inline=False)
        # Kontext
        botctx = context["bot"]
        ctx_text = (
            f"Bot Latency: {botctx['latency']}\n"
            f"Python: {botctx['python']} | discord.py: {botctx['discord_py']}\n"
            f"OS: {botctx['os']} | PID: {botctx['pid']}\n"
            f"Zeit: {botctx['time']}"
        )
        log_embed.add_field(name="Kontext", value=ctx_text, inline=False)

        # Dateien anhängen
        trace_tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt")
        ctx_tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json")
        try:
            trace_tmp.write(full_trace); trace_tmp.close()
            ctx_tmp.write(json.dumps(context, ensure_ascii=False, indent=2)); ctx_tmp.close()
        except Exception:
            try:
                trace_tmp.close(); ctx_tmp.close()
            except Exception:
                pass

        # Senden
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=user_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=user_embed, ephemeral=True)
        except discord.InteractionResponded:
            pass

        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(
                    embed=log_embed,
                    files=[
                        discord.File(trace_tmp.name, filename="traceback.txt"),
                        discord.File(ctx_tmp.name, filename="context.json"),
                    ],
                )
            except Exception:
                pass
        # Clean up
        for fp in (trace_tmp.name, ctx_tmp.name):
            try:
                os.remove(fp)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorCog(bot))
