import logging
import os
import html
import re
import io  # NEW
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, Optional, Literal

import aiohttp
import aiomysql
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from utils.branding import get_current_colour

load_dotenv(dotenv_path="/root/Astra/.env")

POLL_INTERVAL_MINUTES = 1
WEBHOOK_NAME = "Astra-Notifier"

# CHANGED: Wir nutzen eine feste Avatar-URL (deine Vorgabe)
WEBHOOK_AVATAR_URL = "https://cdn.discordapp.com/attachments/1141116983358804117/1425456237230821467/Idee_2_blau2_-_Kopie_512x512.jpg?ex=68e7a712&is=68e65592&hm=fffdefc8e53072f0c967bfedb0353c9b7a6f3c9b87b80de31b2121a45253094f"

YOUTUBE_USE_RSS = False
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams?user_login={login}"
TWITCH_CHANNEL_URL = "https://twitch.tv/{login}"


ASTRA_COLOR = get_current_colour()
TWITCH_COLOR = discord.Colour.from_rgb(145, 70, 255)
YOUTUBE_COLOR = discord.Colour.from_rgb(230, 33, 23)


def astra_embed(
    *,
    title: str,
    description: str = "",
    color: discord.Colour = ASTRA_COLOR,
    author: Optional[discord.abc.User] = None,
    guild: Optional[discord.Guild] = None,
    url: Optional[str] = None,
) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color, url=url)
    e.timestamp = datetime.now(timezone.utc)
    if author:
        e.set_author(name=str(author), icon_url=author.display_avatar.url)
    if guild and guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    if author:
        e.set_footer(text="Astra Notifier • powered by Astra", icon_url=author.display_avatar.url)
    else:
        e.set_footer(text="Astra Notifier • powered by Astra")
    return e


def _format_iso8601_duration(iso: str) -> str:
    hours = minutes = seconds = 0
    num = ""
    for ch in iso:
        if ch.isdigit():
            num += ch
            continue
        if ch in "HMS":
            val = int(num) if num else 0
            if ch == "H":
                hours = val
            elif ch == "M":
                minutes = val
            elif ch == "S":
                seconds = val
            num = ""
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


# --------- Pretty formatting helpers ---------

def _format_int(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)

_LANG_MAP = {
    "de": "Deutsch", "en": "Englisch", "en-gb": "Englisch (UK)", "en-us": "Englisch (US)",
    "fr": "Französisch", "es": "Spanisch", "it": "Italienisch", "pt": "Portugiesisch",
    "pt-br": "Portugiesisch (BR)", "nl": "Niederländisch", "sv": "Schwedisch",
    "no": "Norwegisch", "da": "Dänisch", "fi": "Finnisch", "pl": "Polnisch",
    "cs": "Tschechisch", "sk": "Slowakisch", "hu": "Ungarisch", "tr": "Türkisch",
    "ru": "Russisch", "uk": "Ukrainisch", "zh": "Chinesisch", "ja": "Japanisch",
    "ko": "Koreanisch"
}
def _format_lang(code: Optional[str]) -> str:
    if not code:
        return "—"
    c = str(code).lower()
    return _LANG_MAP.get(c, c)

def _format_ts_utc_with_relative(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            rel = f"vor {secs} Sek."
        elif secs < 3600:
            rel = f"vor {secs//60} Min."
        elif secs < 86400:
            rel = f"vor {secs//3600} Std."
        else:
            rel = f"vor {secs//86400} Tagen"
        return f"{dt:%Y-%m-%d %H:%M} UTC ({rel})"
    except Exception:
        return iso.replace("T", " ").replace("Z", " UTC")

def _clean_youtube_description(desc: str) -> str:
    if not desc:
        return ""
    s = html.unescape(desc)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = "\n".join(line.rstrip() for line in s.split("\n")).strip()
    return s

def _fit_description_for_embed(embed_title: str, description: str, fields: Dict[str, str]) -> str:
    MAX_TOTAL = 6000
    MAX_DESC = 4096
    FOOTER_TEXT = "Astra Notifier • Jetzt reinschauen!"
    other_len = len(embed_title or "") + len(FOOTER_TEXT)
    for k, v in (fields or {}).items():
        other_len += len(str(k)) + len(str(v or ""))
    remaining = max(0, min(MAX_DESC, MAX_TOTAL - other_len))
    if len(description) <= remaining:
        return description
    if remaining <= 3:
        return (description[:remaining]).rstrip()
    return (description[: remaining - 3]).rstrip() + "..."


class Notifier(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not hasattr(bot, "pool") or not isinstance(bot.pool, aiomysql.Pool):
            raise RuntimeError("Dieses Cog erwartet einen globalen aiomysql-Pool in bot.pool")
        self.pool: aiomysql.Pool = bot.pool
        self.http: Optional[aiohttp.ClientSession] = None
        self._webhook_cache: Dict[Tuple[int, int], discord.Webhook] = {}
        self._twitch_token: Optional[str] = None
        self._twitch_token_expire: Optional[datetime] = None

    async def cog_load(self):
        self.http = aiohttp.ClientSession()
        self.check_for_updates.change_interval(minutes=POLL_INTERVAL_MINUTES)
        self.check_for_updates.start()

    async def cog_unload(self):
        self.check_for_updates.cancel()
        if self.http:
            await self.http.close()

    # ---------- DB helpers ----------
    async def subscribe(
        self,
        guild_id: int,
        platform: str,
        channel_id: int,
        content_id: str,
        ping_role_id: Optional[int] = None,
    ):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO subscriptions
                (guild_id, discord_channel_id, platform, content_id, ping_role_id, last_item_id, last_sent_at)
                    VALUES (%s, %s, %s, %s, %s, NULL, NULL) AS new
                ON DUPLICATE KEY UPDATE ping_role_id = new.ping_role_id,
                                        last_item_id = IF(subscriptions.content_id <> new.content_id, NULL,
                                                          subscriptions.last_item_id),
                                        last_sent_at = IF(subscriptions.content_id <> new.content_id, NULL,
                                                          subscriptions.last_sent_at),
                                        content_id   = new.content_id
                """,
                (str(guild_id), str(channel_id), platform, content_id, ping_role_id),
            )

    async def delete_subscription(self, guild_id: int, platform: str, channel_id: int, content_id: str) -> int:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM subscriptions WHERE guild_id=%s AND platform=%s AND discord_channel_id=%s AND content_id=%s",
                (str(guild_id), platform, str(channel_id), content_id),
            )
            return cur.rowcount

    async def set_enabled(self, guild_id: int, platform: str, enabled: bool):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO notifier_settings (guild_id, platform, enabled)
                VALUES (%s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE enabled = new.enabled
                """,
                (str(guild_id), platform, 1 if enabled else 0),
            )

    async def is_enabled(self, guild_id: int, platform: str) -> bool:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT enabled FROM notifier_settings WHERE guild_id=%s AND platform=%s", (str(guild_id), platform))
            row = await cur.fetchone()
        return True if row is None else bool(row[0])

    async def _update_last_sent(
        self,
        guild_id: int,
        platform: str,
        channel_id: int,
        content_id: str,
        item_id: str,
    ):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE subscriptions
                   SET last_item_id=%s, last_sent_at=%s
                 WHERE guild_id=%s AND platform=%s AND discord_channel_id=%s AND content_id=%s
                """,
                (item_id, now, str(guild_id), platform, str(channel_id), content_id),
            )

    # ---------- Poll Loop ----------
    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def check_for_updates(self):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT guild_id, discord_channel_id, platform, content_id, ping_role_id, last_item_id FROM subscriptions"
            )
            subs = await cur.fetchall()

        for guild_id, channel_id, platform, content_id, ping_role_id, last_item_id in subs:
            try:
                g_id = int(guild_id)
                guild = self.bot.get_guild(g_id)
                if guild is None:
                    # Bot ist nicht mehr auf dem Server -> sauber überspringen
                    continue

                if not await self.is_enabled(g_id, platform):
                    continue
                if platform == "youtube":
                    await self._check_youtube(content_id, g_id, int(channel_id), ping_role_id, last_item_id)
                elif platform == "twitch":
                    await self._check_twitch(content_id, g_id, int(channel_id), ping_role_id, last_item_id)
            except (discord.NotFound, discord.Forbidden) as e:
                logging.warning(f"[Notifier] Nicht verfügbar / keine Berechtigung bei {platform}:{content_id} (Guild: {guild_id}) → {e}")
            except discord.HTTPException as e:
                logging.warning(f"[Notifier] Discord HTTP-Fehler bei {platform}:{content_id} (Guild: {guild_id}) → {e}")
            except Exception as e:
                g = self.bot.get_guild(int(guild_id))
                guild_name = f"{g.name} ({g.id})" if g else str(guild_id)
                logging.exception(f"[Notifier] Fehler bei {platform}:{content_id} in {guild_name} → {e}")

    @check_for_updates.before_loop
    async def before_check_for_updates(self):
        await self.bot.wait_until_ready()

    @check_for_updates.error
    async def check_for_updates_error(self, error: Exception):
        logging.error(f"[Notifier] Unerwarteter Fehler im Task check_for_updates: {error}", exc_info=error)

    # ---------- YouTube ----------
    async def _resolve_youtube_channel_id(self, raw: str) -> Optional[str]:
        s = raw.strip()
        if s.startswith("UC") and len(s) >= 16:
            return s
        if s.startswith("@"):
            if not YOUTUBE_API_KEY:
                return None
            params = {"part": "id", "forHandle": s, "key": YOUTUBE_API_KEY}
            async with self.http.get(YOUTUBE_CHANNELS_URL, params=params) as resp:
                data = await resp.json()
            items = data.get("items", [])
            return items[0]["id"] if items else None
        if "youtube.com" in s or "youtu.be" in s:
            from urllib.parse import urlparse
            p = urlparse(s)
            parts = [x for x in p.path.split("/") if x]
            if len(parts) >= 2 and parts[0].lower() == "channel" and parts[1].startswith("UC"):
                return parts[1]
            if parts and parts[0].startswith("@"):
                return await self._resolve_youtube_channel_id(parts[0])
        if not YOUTUBE_API_KEY:
            return None
        params = {"part": "snippet", "q": s, "type": "channel", "maxResults": 1, "key": YOUTUBE_API_KEY}
        async with self.http.get(YOUTUBE_SEARCH_URL, params=params) as resp:
            data = await resp.json()
        items = data.get("items", [])
        return items[0]["id"]["channelId"] if items else None

    async def _get_youtube_video_details(self, video_id: str) -> Dict[str, str]:
        if not YOUTUBE_API_KEY:
            return {}
        params = {"part": "contentDetails,statistics,snippet", "id": video_id, "key": YOUTUBE_API_KEY, "maxResults": 1}
        async with self.http.get(YOUTUBE_VIDEOS_URL, params=params) as resp:
            data = await resp.json()
        items = data.get("items", [])
        if not items:
            return {}
        it = items[0]
        details = it.get("contentDetails", {})
        stats = it.get("statistics", {})
        snip = it.get("snippet", {})
        duration = _format_iso8601_duration(details.get("duration", "")) if details.get("duration") else "—"
        views = stats.get("viewCount")
        ch_thumb = snip.get("thumbnails", {}).get("high", snip.get("thumbnails", {}).get("default", {})).get("url")
        return {"duration": duration, "views": views, "channel_thumb": ch_thumb}

    async def _check_youtube(self, yt_channel_id: str, guild_id: int, target_channel_id: int, ping_role_id: Optional[int], last_item_id: Optional[str]):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(target_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(target_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info(f"[Notifier] YouTube Zielkanal {target_channel_id} in {guild.name} nicht erreichbar.")
                return
        if not isinstance(channel, discord.TextChannel):
            logging.info(f"[Notifier] YouTube Zielkanal {target_channel_id} in {guild.name} nicht gefunden/kein Textkanal.")
            return

        published_after = (datetime.now(timezone.utc) - timedelta(minutes=POLL_INTERVAL_MINUTES))
        items = []

        if YOUTUBE_USE_RSS:
            url = YOUTUBE_RSS_URL.format(channel_id=yt_channel_id)
            async with self.http.get(url) as resp:
                xml = await resp.text()
            entries = re.findall(
                r"<yt:videoId>(.*?)</yt:videoId>.*?<published>(.*?)</published>.*?<title>(.*?)</title>",
                xml, flags=re.S
            )
            parsed = []
            for vid, published, title in entries:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt > published_after:
                    parsed.append((pub_dt.isoformat().replace("+00:00", "Z"), vid, title))
            parsed.sort(key=lambda t: t[0])
            for published_at, vid, title in parsed:
                items.append({
                    "id": {"videoId": vid},
                    "snippet": {"title": title, "publishedAt": published_at}
                })
        else:
            if not YOUTUBE_API_KEY:
                return
            params = {
                "part": "snippet",
                "channelId": yt_channel_id,
                "order": "date",
                "type": "video",
                "publishedAfter": published_after.isoformat().replace("+00:00", "Z"),
                "maxResults": 5,
                "key": YOUTUBE_API_KEY,
            }
            async with self.http.get(YOUTUBE_SEARCH_URL, params=params) as resp:
                data = await resp.json()
            items = data.get("items", [])
            items.sort(key=lambda it: it["snippet"].get("publishedAt", ""))

        for item in items:
            vid = item["id"]["videoId"]
            if last_item_id and vid == last_item_id:
                continue
            snip = item["snippet"]
            title = snip.get("title", "Neues Video")
            raw_desc = snip.get("description", "")
            channel_title = snip.get("channelTitle", "YouTube")
            published_at = snip.get("publishedAt")

            details = await self._get_youtube_video_details(vid)
            fields = {
                "Kanal": channel_title,
                "Veröffentlicht": _format_ts_utc_with_relative(published_at) if published_at else "—",
                "Dauer": details.get("duration", "—"),
                "Aufrufe": _format_int(details.get("views", "—")),
            }

            embed_title = f"🎥 Neues Video: {title}"
            cleaned = _clean_youtube_description(raw_desc or "Ein neues Video ist online!")
            desc = _fit_description_for_embed(embed_title, cleaned, fields)

            thumb = snip.get("thumbnails", {}).get("high", snip.get("thumbnails", {}).get("default", {})).get("url", "")

            # (Optional) Du kannst auch YouTube-Thumbnails als Attachment senden – hier belasse ich es bei URL.
            await self._send_webhook(
                channel,
                title=embed_title,
                description=desc,
                thumbnail=thumb,
                url=YOUTUBE_VIDEO_URL.format(video_id=vid),
                color=YOUTUBE_COLOR,
                ping_role_id=ping_role_id,
                author=(channel_title, details.get("channel_thumb")),
                fields=fields,
                button_label="Zum Video",
            )
            await self._update_last_sent(guild_id, "youtube", target_channel_id, yt_channel_id, vid)
            break

    # ---------- Twitch ----------
    async def _check_twitch(self, login: str, guild_id: int, target_channel_id: int, ping_role_id: Optional[int], last_item_id: Optional[str]):
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(target_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(target_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logging.info(f"[Notifier] Twitch Zielkanal {target_channel_id} in {guild.name} nicht erreichbar.")
                return
        if not isinstance(channel, discord.TextChannel):
            logging.info(f"[Notifier] Twitch Zielkanal {target_channel_id} in {guild.name} nicht gefunden/kein Textkanal.")
            return

        token = await self._get_twitch_token()
        headers = {"Client-Id": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}

        async with self.http.get(TWITCH_STREAMS_URL.format(login=login), headers=headers) as resp:
            if resp.status != 200:
                logging.info(f"[Notifier] Twitch streams Fehler {resp.status}: {await resp.text()}")
                return
            data = await resp.json()

        streams = data.get("data", [])
        if not streams:
            return

        s = streams[0]
        stream_id = s.get("id")
        if stream_id and last_item_id and str(stream_id) == str(last_item_id):
            return

        title = s.get("title", f"{login} ist live!")

        # CHANGED: Thumbnail laden und als Attachment senden (gegen Discord Cache)
        thumb = s["thumbnail_url"].replace("{width}", "1280").replace("{height}", "720")
        stream_id_str = str(s.get("id", ""))
        started_at = str(s.get("started_at", ""))
        started_digits = "".join(ch for ch in started_at if ch.isdigit())
        cb = f"{stream_id_str}{started_digits}" or str(int(datetime.now(timezone.utc).timestamp()))
        sep = "&" if "?" in thumb else "?"
        thumb = f"{thumb}{sep}cb={cb}"

        # Bild herunterladen
        async with self.http.get(thumb) as r:
            if r.status != 200:
                logging.info(f"[Notifier] Konnte Twitch-Thumbnail nicht laden: {r.status}")
                return
            img_bytes = await r.read()
        filename = f"twitch_{login}_{cb}.jpg"
        file = discord.File(io.BytesIO(img_bytes), filename=filename)

        fields = {
            "Spiel": s.get("game_name") or "—",
            "Zuschauer": _format_int(s.get("viewer_count", "—")),
            "Gestartet": _format_ts_utc_with_relative(s.get("started_at")),
            "Sprache": _format_lang(s.get("language")),
        }
        await self._send_webhook(
            channel,
            title=f"🟣 {login} ist jetzt LIVE",
            description=title,
            thumbnail=f"attachment://{filename}",  # CHANGED
            url=TWITCH_CHANNEL_URL.format(login=login),
            color=TWITCH_COLOR,
            ping_role_id=ping_role_id,
            author=(login, None),
            fields=fields,
            button_label="Zum Stream",
            file=file,  # CHANGED
        )
        if stream_id_str:
            await self._update_last_sent(guild_id, "twitch", target_channel_id, login, stream_id_str)

    # ---------- Webhooks ----------
    async def _send_webhook(
        self,
        channel: discord.TextChannel,
        *,
        title: str,
        description: str,
        thumbnail: str,
        url: str,
        color: discord.Colour,
        ping_role_id: Optional[int] = None,
        author: Optional[Tuple[str, Optional[str]]] = None,
        fields: Optional[Dict[str, str]] = None,
        button_label: Optional[str] = None,
        file: Optional[discord.File] = None,  # NEW
    ):
        webhook = await self._get_or_create_webhook(channel.guild.id, channel.id)
        if not webhook:
            return

        e = discord.Embed(title=title, description=(description or "")[:4096], url=url, color=color)
        e.timestamp = datetime.now(timezone.utc)
        if thumbnail:
            e.set_image(url=thumbnail)  # funktioniert auch mit "attachment://filename"
        if author:
            name, icon = author
            if name:
                e.set_author(name=name, icon_url=icon) if icon else e.set_author(name=name)
        if fields:
            for k, v in fields.items():
                e.add_field(name=str(k), value=str(v) if v is not None else "—", inline=True)
        e.set_footer(text="Astra Notifier • Jetzt reinschauen!")

        view = None
        if button_label and url:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label=button_label, url=url))

        content = None
        allowed = discord.AllowedMentions(roles=True)
        if ping_role_id:
            role = channel.guild.get_role(int(ping_role_id))
            if role:
                content = role.mention

        try:
            await webhook.send(
                embed=e,
                content=content,
                allowed_mentions=allowed,
                username=WEBHOOK_NAME,
                view=view,
                file=file,  # NEW
            )
        except discord.NotFound:
            # Webhook wurde möglicherweise auf Discord gelöscht -> Cache leeren
            self._webhook_cache.pop((channel.guild.id, channel.id), None)
            raise

    async def _get_or_create_webhook(self, guild_id: int, channel_id: int):
        key = (guild_id, channel_id)
        if key in self._webhook_cache:
            return self._webhook_cache[key]

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        if not isinstance(channel, discord.TextChannel):
            return None

        try:
            for wh in await channel.webhooks():
                if wh.name == WEBHOOK_NAME:
                    await self._ensure_webhook_avatar(wh)  # CHANGED: Avatar aktualisieren
                    self._webhook_cache[key] = wh
                    return wh

            wh = await channel.create_webhook(name=WEBHOOK_NAME, reason="Astra Notifier")
            await self._ensure_webhook_avatar(wh)
            self._webhook_cache[key] = wh
            return wh
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logging.warning(f"[Notifier] Konnte Webhook in {channel.name} ({guild_id}) nicht abrufen/erstellen: {e}")
            return None

    async def _ensure_webhook_avatar(self, webhook: discord.Webhook):
        """Setzt/aktualisiert das Avatar für bestehende/neu erstellte Webhooks mit hartem Cache-Refresh."""
        try:
            if WEBHOOK_AVATAR_URL:
                # Bild laden
                async with self.http.get(WEBHOOK_AVATAR_URL) as r:
                    if r.status != 200:
                        logging.info(f"[Notifier] Konnte Webhook-Avatar nicht laden: {r.status}")
                        return
                    avatar_bytes = await r.read()
                # harter Refresh (Cache umgehen)
                await webhook.edit(avatar=None, reason="Reset webhook avatar cache")
                await webhook.edit(name=WEBHOOK_NAME, avatar=avatar_bytes, reason="Set webhook avatar")
        except Exception as e:
            logging.info(f"[Notifier] Konnte Webhook-Avatar nicht setzen: {e}")

    async def _get_twitch_token(self):
        now = datetime.now(timezone.utc)
        if self._twitch_token and self._twitch_token_expire and self._twitch_token_expire > now + timedelta(minutes=2):
            return self._twitch_token

        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            raise RuntimeError("TWITCH_CLIENT_ID oder TWITCH_CLIENT_SECRET fehlt.")

        data = {"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}
        async with self.http.post(TWITCH_TOKEN_URL, data=data) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Twitch Token-Fehler {resp.status}: {await resp.text()}")
            token_data = await resp.json()

        self._twitch_token = token_data.get("access_token", "")
        self._twitch_token_expire = now + timedelta(seconds=int(token_data.get("expires_in", 3600)))
        if not self._twitch_token:
            raise RuntimeError("Kein access_token in Token-Antwort.")
        return self._twitch_token


@app_commands.guild_only()
class Benachrichtigung(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="benachrichtigung", description="Benachrichtigungen für YouTube & Twitch")
        self.bot = bot

    @app_commands.command(name="info", description="Zeigt Informationen und aktive Benachrichtigungen an")
    async def info(self, interaction: discord.Interaction):
        """Zeigt alle aktiven YouTube- und Twitch-Abos dieses Servers."""
        cog: Optional[Notifier] = interaction.client.get_cog("Notifier")  # type: ignore
        if not cog:
            return await interaction.response.send_message(
                embed=astra_embed(
                    title="❌ Notifier nicht bereit",
                    description="Bitte versuche es gleich erneut.",
                    author=interaction.user,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )

        # --- Datenbankabfrage: alle Subscriptions dieses Servers holen
        async with cog.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT platform, content_id, discord_channel_id, ping_role_id, last_item_id, last_sent_at
                  FROM subscriptions
                 WHERE guild_id=%s
                """,
                (str(interaction.guild_id),),
            )
            subs = await cur.fetchall()

        # --- Embed vorbereiten
        desc = (
            "Dieser Notifier überprüft regelmäßig Twitch-Streams und YouTube-Kanäle "
            "und sendet automatisch eine Nachricht, wenn jemand live geht oder ein neues Video hochlädt.\n\n"
            "🔔 **Befehle:**\n"
            "• `/benachrichtigung twitch` – Twitch-Kanäle hinzufügen oder entfernen\n"
            "• `/benachrichtigung youtube` – YouTube-Kanäle hinzufügen oder entfernen\n\n"
            "Hier siehst du alle aktuell aktiven Benachrichtigungen:"
        )

        embed = astra_embed(
            title="📢 Astra Notifier Info",
            description=desc,
            color=discord.Colour.blurple(),
            author=interaction.user,
            guild=interaction.guild,
        )

        if not subs:
            embed.add_field(
                name="Keine aktiven Benachrichtigungen",
                value="🚫 Es sind momentan keine YouTube- oder Twitch-Kanäle abonniert.",
                inline=False,
            )
        else:
            twitch_list = []
            yt_list = []
            for platform, content_id, ch_id, role_id, last_item, last_sent in subs:
                channel_mention = f"<#{ch_id}>"
                ping_text = f"<@&{role_id}>" if role_id else "—"
                last_line = f"🕒 {last_sent:%Y-%m-%d %H:%M}" if last_sent else "—"
                line = f"**{content_id}** → {channel_mention}\n🔔 Ping: {ping_text}\nZuletzt gesendet: {last_line}"

                if platform == "twitch":
                    twitch_list.append(line)
                elif platform == "youtube":
                    yt_list.append(line)

            if yt_list:
                embed.add_field(
                    name="📺 YouTube-Abos",
                    value="\n\n".join(yt_list),
                    inline=False,
                )
            if twitch_list:
                embed.add_field(
                    name="🟣 Twitch-Abos",
                    value="\n\n".join(twitch_list),
                    inline=False,
                )

        embed.set_footer(text="Astra Notifier • Statusübersicht")

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="youtube", description="YouTube-Kanal hinzufügen oder entfernen")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        aktion="Hinzufügen oder Entfernen",
        channel="Discord-Kanal für Benachrichtigungen",
        channelname="YouTube-Channel (ID/Handle/URL/Name)",
        rolle="(Optional) Rolle, die gepingt wird",
    )
    async def youtube(
        self,
        interaction: discord.Interaction,
        aktion: Literal["Hinzufügen", "Entfernen"],
        channel: discord.TextChannel,
        channelname: str,
        rolle: Optional[discord.Role] = None,
    ):
        cog: Optional[Notifier] = interaction.client.get_cog("Notifier")  # type: ignore
        if not cog:
            return await interaction.response.send_message(
                embed=astra_embed(title="❌ Notifier nicht bereit", description="Bitte versuche es gleich erneut.", author=interaction.user, guild=interaction.guild),
                ephemeral=True,
            )

        if aktion == "Hinzufügen":
            yt_id = await cog._resolve_youtube_channel_id(channelname) or channelname
            await cog.subscribe(interaction.guild_id, "youtube", channel.id, yt_id, rolle.id if rolle else None)
            await cog.set_enabled(interaction.guild_id, "youtube", True)
            await interaction.response.send_message(
                embed=astra_embed(
                    title="✅ YouTube-Abo hinzugefügt",
                    description=f"**Channel:** `{channelname}` → `{yt_id}`\n**Ziel:** {channel.mention}\n**Ping:** {rolle.mention if rolle else '—'}\n**Modus:** {'RSS' if YOUTUBE_USE_RSS else 'YouTube Data API'}",
                    color=YOUTUBE_COLOR,
                    author=interaction.user,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        else:
            await cog.delete_subscription(interaction.guild_id, "youtube", channel.id, channelname)
            await interaction.response.send_message(
                embed=astra_embed(title="🗑️ YouTube-Abo entfernt", description=f"**Channel:** `{channelname}`\n**Ziel:** {channel.mention}", color=YOUTUBE_COLOR, author=interaction.user, guild=interaction.guild),
                ephemeral=True,
            )

    @app_commands.command(name="twitch", description="Twitch-Kanal hinzufügen oder entfernen")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        aktion="Hinzufügen oder Entfernen",
        channel="Discord-Kanal für Benachrichtigungen",
        channelname="Twitch-Channelname",
        rolle="(Optional) Rolle, die gepingt wird",
    )
    async def twitch(
        self,
        interaction: discord.Interaction,
        aktion: Literal["Hinzufügen", "Entfernen"],
        channel: discord.TextChannel,
        channelname: str,
        rolle: Optional[discord.Role] = None,
    ):
        cog: Optional[Notifier] = interaction.client.get_cog("Notifier")  # type: ignore
        if not cog:
            return await interaction.response.send_message(
                embed=astra_embed(title="❌ Notifier nicht bereit", description="Bitte versuche es gleich erneut.", author=interaction.user, guild=interaction.guild),
                ephemeral=True,
            )

        login = channelname.lower()
        if aktion == "Hinzufügen":
            await cog.subscribe(interaction.guild_id, "twitch", channel.id, login, rolle.id if rolle else None)
            await cog.set_enabled(interaction.guild_id, "twitch", True)
            await interaction.response.send_message(
                embed=astra_embed(
                    title="✅ Twitch-Abo hinzugefügt",
                    description=f"**Login:** `{login}`\n**Ziel:** {channel.mention}\n**Ping:** {rolle.mention if rolle else '—'}",
                    color=TWITCH_COLOR,
                    author=interaction.user,
                    guild=interaction.guild,
                ),
                ephemeral=True,
            )
        else:
            await cog.delete_subscription(interaction.guild_id, "twitch", channel.id, login)
            await interaction.response.send_message(
                embed=astra_embed(title="🗑️ Twitch-Abo entfernt", description=f"**Login:** `{login}`\n**Ziel:** {channel.mention}", color=TWITCH_COLOR, author=interaction.user, guild=interaction.guild),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifier(bot))
    try:
        bot.tree.add_command(Benachrichtigung(bot))
    except Exception:
        pass
