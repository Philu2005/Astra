from __future__ import annotations
import asyncio
import hashlib
import time
import typing as T
import uuid
import io
import zstandard as zstd
import aiohttp
import aiomysql
import discord
from discord import app_commands
import gzip
from discord.ext import commands


def is_guild_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)

# ---------------- JSON & Kompression ----------------
try:
    import orjson
    def dumps(obj: T.Any) -> bytes:
        return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
    def loads(b: bytes) -> T.Any:
        return orjson.loads(b)
except ImportError:
    import json
    def dumps(obj: T.Any) -> bytes:
        return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    def loads(b: bytes) -> T.Any:
        return json.loads(b.decode())

try:
    import zstandard as zstd
    _HAS_ZSTD = True
except ImportError:
    import gzip
    _HAS_ZSTD = False

class BackupFileFormat(T.TypedDict):
    ext: str
    compress: T.Callable[[bytes], bytes]
    decompress: T.Callable[[bytes], bytes] | None


BACKUP_EXPORT_FORMATS: dict[str, BackupFileFormat] = {
    "zst": {
        "ext": "zst.json",
        "compress": lambda b: zstd.ZstdCompressor(level=12).compress(b),
        "decompress": lambda b: zstd.ZstdDecompressor().decompress(b),
    },
    "gz": {
        "ext": "gz.json",
        "compress": gzip.compress,
        "decompress": gzip.decompress,
    },
    "json": {
        "ext": "json",
        "compress": lambda b: b,
        "decompress": None,
    },
}


# ---------------- Einstellungen ----------------
BACKUP_VERSION = 1
RETENTION_DAYS = 7            # Jobs: done/error älter als X Tage löschen
BACKUP_RETENTION_DAYS = 7     # Backups älter als X Tage löschen

# ---------------- Helfer ----------------
def b58(b: bytes) -> str:
    alphabet = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    n = int.from_bytes(b, 'big')
    out = bytearray()
    while n:
        n, r = divmod(n, 58)
        out.append(alphabet[r])
    return out[::-1].decode() or "1"

def blake128(b: bytes) -> bytes:
    return hashlib.blake2b(b, digest_size=16).digest()

def gen_backup_code() -> str:
    """Erzeugt einen eindeutigen zufälligen Backup-Code (Base58)."""
    return b58(uuid.uuid4().bytes)

async def gentle_sleep():
    await asyncio.sleep(0.3)

def progress_bar(step: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "—" * width
    filled = int(round(width * step / max(1, total)))
    return "█" * filled + "░" * (width - filled)

def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024

def join_limit(names: list[str], *, max_len: int = 900) -> str:
    out, used = [], 0
    for i, name in enumerate(names):
        add = (", " if out else "") + name
        if used + len(add) > max_len:
            rest = len(names) - i
            if rest > 0:
                out.append(f" … +{rest} weitere")
            break
        out.append(add if out else name)
        used += len(add)
    return "".join(out) if out else "—"

def compute_includes(payload: dict) -> str:
    parts = []

    if payload.get("roles"):
        parts.append("roles")

    has_channels = False
    has_overwrites = False

    # Neues Format
    for cat in payload.get("categories", []) or []:
        has_channels = True
        if cat.get("overwrites"):
            has_overwrites = True
        for ch in cat.get("channels", []):
            has_channels = True
            if ch.get("overwrites"):
                has_overwrites = True

    for ch in payload.get("uncategorized", []) or []:
        has_channels = True
        if ch.get("overwrites"):
            has_overwrites = True

    # Altes Format
    for ch in payload.get("channels", []) or []:
        has_channels = True
        if ch.get("overwrites"):
            has_overwrites = True

    if has_channels:
        parts.append("channels")
    if has_overwrites:
        parts.append("overwrites")

    return ",".join(parts)

def build_progress_embed(*, title: str, step: int, total: int, status: str,
                         color: discord.Color, error: str | None = None) -> discord.Embed:
    pct = 0 if total == 0 else min(100, int(step * 100 / max(1, total)))
    emb = discord.Embed(
        title=title,
        description=f"{progress_bar(step, total)}  **{pct}%**",
        color=color
    )
    emb.add_field(name="Status", value=status, inline=False)
    emb.add_field(name="Fortschritt", value=f"{step} / {total} Schritte", inline=True)
    if error:
        emb.add_field(name="Hinweis", value=error[:1000], inline=False)
    return emb


class BackupListView(discord.ui.View):
    def __init__(self, entries: list[dict], build_embed, *, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.entries = entries
        self.index = 0
        self.build_embed = build_embed

        # Dropdown (max. 25 Optionen)
        options = []
        for i, e in enumerate(entries[:25]):
            options.append(discord.SelectOption(
                label=e["code"],
                description=f"v{e['version']} • {e['size']} • {e['roles_count']} Rollen, {e['channels_total']} Channels",
                value=str(i)
            ))
        sel = discord.ui.Select(placeholder="Backup auswählen …", options=options, min_values=1, max_values=1)

        async def _on_select(inter: discord.Interaction):
            self.index = int(sel.values[0])
            await inter.response.edit_message(
                embed=self.build_embed(self.entries[self.index], self.index, len(self.entries)),
                view=self
            )
        sel.callback = _on_select
        self.add_item(sel)

    @discord.ui.button(label="◀︎ Zurück", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index - 1) % len(self.entries)
        await interaction.response.edit_message(
            embed=self.build_embed(self.entries[self.index], self.index, len(self.entries)),
            view=self
        )

    @discord.ui.button(label="Weiter ▶︎", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.index = (self.index + 1) % len(self.entries)
        await interaction.response.edit_message(
            embed=self.build_embed(self.entries[self.index], self.index, len(self.entries)),
            view=self
        )

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True


def esc_md(s: str) -> str:
    return discord.utils.escape_markdown(s or "")

def fmt_mention_role(guild: discord.Guild, name: str) -> str:
    r = discord.utils.find(lambda rr: rr.name == name, guild.roles)
    return r.mention if r else esc_md(name)

def fmt_mention_channel(guild: discord.Guild, name: str, ctype: int | None) -> str:
    # Versuche, aktuellen Channel per Name zu finden und zu pingen
    if name:
        ch = discord.utils.find(lambda cc: cc.name == name, guild.channels)
        if ch and hasattr(ch, "mention"):
            return ch.mention
    # Fallback nach Typ
    if ctype == discord.ChannelType.voice.value:
        return f"🔊 {esc_md(name)}"
    elif ctype == discord.ChannelType.stage_voice.value:
        return f"🎤 {esc_md(name)}"
    elif ctype == discord.ChannelType.forum.value:
        return f"🧵 {esc_md(name)}"
    elif ctype == discord.ChannelType.news.value:
        return f"📣 {esc_md(name)}"
    else:
        return f"# {esc_md(name)}"

def join_vertical(lines: list[str], *, max_len: int = 1000) -> tuple[str, int]:
    """Gibt multiline-String zurück; schneidet ab und liefert Restanzahl."""
    out, used, rest = [], 0, 0
    for i, line in enumerate(lines):
        add = ("" if not out else "\n") + line
        if used + len(add) > max_len:
            rest = len(lines) - i
            break
        out.append(add if not out else line)
        used += len(add)
    return ("\n".join(out) if out else "—"), rest

def build_category_tree_block(guild: discord.Guild, chans: list[dict]) -> str:
    # Gruppiere nach Kategorie
    cats: dict[str | None, list[dict]] = {}
    for c in chans:
        parent = c.get("parent_name")
        cats.setdefault(parent, []).append(c)

    # Sortierung
    def sort_key(c): return 0 if c.get("type") == discord.ChannelType.category.value else 1, str(c.get("name", "")).casefold()

    lines: list[str] = []
    # Kategorien (ohne None) zuerst
    for cat_name in sorted([k for k in cats.keys() if k], key=lambda s: s.casefold()):
        lines.append(f"**{esc_md(cat_name)}**")
        for ch in sorted([c for c in cats[cat_name] if c.get('type') != discord.ChannelType.category.value], key=sort_key):
            lines.append(f"└─ {fmt_mention_channel(guild, ch.get('name',''), ch.get('type'))}")

    # Unkategorisiert
    if None in cats:
        lines.append("**Unkategorisiert**")
        for ch in sorted([c for c in cats[None] if c.get('type') != discord.ChannelType.category.value], key=sort_key):
            lines.append(f"└─ {fmt_mention_channel(guild, ch.get('name',''), ch.get('type'))}")

    text, rest = join_vertical(lines, max_len=1000)
    if rest:
        text += f"\n… **+{rest} weitere**"
    return text

def build_vertical_list_role_mentions(guild: discord.Guild, names: list[str]) -> str:
    lines = [fmt_mention_role(guild, n) for n in names]
    text, rest = join_vertical(lines, max_len=1000)
    if rest:
        text += f"\n… **+{rest} weitere**"
    return text

def build_vertical_list_mentions(guild: discord.Guild, names: list[str], *, prefix_channel_type: int | None = None) -> str:
    lines = [fmt_mention_channel(guild, n, prefix_channel_type) for n in names]
    text, rest = join_vertical(lines, max_len=1000)
    if rest:
        text += f"\n… **+{rest} weitere**"
    return text

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
# =====================================================================
# Cog: DB, Worker, Restore/Undo-Logik, Fortschritt & Aufräumen
# =====================================================================
class BackupCog(commands.Cog):
    """Hintergrund-Logik & Jobs für das Astra Backup System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: aiomysql.Pool = getattr(bot, "pool", None)
        if self.pool is None:
            raise RuntimeError("BackupCog benötigt bot.pool (aiomysql.Pool)")
        self.guild_locks: dict[int, asyncio.Lock] = {}
        self.job_worker_task: asyncio.Task | None = None
        self.http: aiohttp.ClientSession | None = None
        self._last_embed_edit: dict[int, float] = {}  # job_id -> last edit timestamp

    async def cog_load(self):
        await self._mark_stale_jobs()
        await self._prune_jobs_time_based()
        await self._prune_backups_time_based()
        self.job_worker_task = asyncio.create_task(self._job_worker_loop())
        self.http = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.job_worker_task:
            self.job_worker_task.cancel()
        if self.http:
            await self.http.close()

    # ---------- Pruning ----------
    async def _mark_stale_jobs(self):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "UPDATE backup_jobs SET status='error', last_error='Bot restart' WHERE status='running'"
            )
            await conn.commit()

    async def _prune_jobs_time_based(self):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM backup_jobs
                WHERE status IN ('done','error')
                  AND created_at < NOW() - INTERVAL %s DAY
                """,
                (RETENTION_DAYS,),
            )
            await conn.commit()

    async def _prune_backups_time_based(self):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM backups
                WHERE created_at < NOW() - INTERVAL %s DAY
                """,
                (BACKUP_RETENTION_DAYS,),
            )
            await conn.commit()

    # ---------- Job-Queue ----------
    async def _queue_job(self, guild_id: int, type_: str, code: str | None,
                         *, status_channel_id: int | None = None, status_message_id: int | None = None) -> int:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO backup_jobs (guild_id, code, type, status_channel_id, status_message_id) VALUES (%s,%s,%s,%s,%s)",
                (guild_id, code, type_, status_channel_id, status_message_id)
            )
            job_id = cur.lastrowid
            await conn.commit()
            return job_id

    async def _update_job(self, job_id: int, **fields):
        if not fields:
            return
        parts = ", ".join(f"{k}=%s" for k in fields)
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(f"UPDATE backup_jobs SET {parts} WHERE job_id=%s", (*fields.values(), job_id))
            await conn.commit()

    async def _delete_job_row(self, job_id: int):
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM backup_jobs WHERE job_id=%s", (job_id,))
            await conn.commit()

    async def _fetch_job(self, job_id: int) -> dict | None:
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM backup_jobs WHERE job_id=%s", (job_id,))
            return await cur.fetchone()

    async def _fetch_last_restore_job(self, guild_id: int) -> dict | None:
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM backup_jobs WHERE guild_id=%s AND type='restore' ORDER BY created_at DESC LIMIT 1",
                (guild_id,)
            )
            return await cur.fetchone()

    async def _fetch_last_job_for_guild(self, guild_id: int) -> dict | None:
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM backup_jobs WHERE guild_id=%s ORDER BY created_at DESC LIMIT 1",
                (guild_id,)
            )
            return await cur.fetchone()

    async def _fetch_pending_jobs(self) -> list[dict]:
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM backup_jobs WHERE status='pending' ORDER BY created_at ASC")
            return await cur.fetchall()

    async def _job_worker_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            jobs = await self._fetch_pending_jobs()
            for job in jobs:
                guild_id = job["guild_id"]
                self.guild_locks.setdefault(guild_id, asyncio.Lock())
                asyncio.create_task(self._run_job(job))
            await asyncio.sleep(5)

    async def _run_job(self, job: dict):
        guild_id = job["guild_id"]
        lock = self.guild_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            await self._update_job(job["job_id"], status="running")
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    raise RuntimeError("Guild nicht gefunden oder Bot nicht drauf.")

                if job["type"] == "restore":
                    data, _ = await self._fetch_backup(job["code"])
                    created_objs = await self._restore_to_guild(guild, data, job["job_id"])
                    await self._update_job(job["job_id"], status="done", created_objects=dumps(created_objs).decode())
                    await self._edit_progress_embed(job["job_id"], final_status="Fertig", color=discord.Colour.blue())

                elif job["type"] == "undo":
                    await self._undo_restore(guild, job)
                    await self._update_job(job["job_id"], status="done")
                    await self._edit_progress_embed(job["job_id"], final_status="Undo abgeschlossen", color=discord.Colour.blue())
                    await self._delete_job_row(job["job_id"])

                elif job["type"] == "create":
                    await self._update_job(job["job_id"], status="done")
                    await self._delete_job_row(job["job_id"])

            except Exception as e:
                await self._update_job(job["job_id"], status="error", last_error=str(e))
                await self._edit_progress_embed(job["job_id"], final_status=f"Fehler: {e}", color=discord.Colour.red())
            finally:
                try:
                    await self._prune_jobs_time_based()
                    await self._prune_backups_time_based()
                except Exception:
                    pass

    # ---------- Backup I/O ----------
    async def _store_backup(self, guild_id: int, payload: dict) -> str:
        raw = dumps(payload)
        digest = blake128(raw)
        blob = zstd.ZstdCompressor(level=12).compress(raw) if _HAS_ZSTD else gzip.compress(raw)  # type: ignore

        includes = compute_includes(payload)  # NEW: was ist drin? -> "roles,channels,overwrites"

        # Garantiert eindeutiger Code (mehrere Versuche)
        for _ in range(5):
            code = gen_backup_code()
            try:
                async with self.pool.acquire() as conn, conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO backups (code, guild_id, includes, version, size_bytes, `hash`, `data_blob`)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (code, guild_id, includes, BACKUP_VERSION, len(blob), digest, blob)
                    )
                    await conn.commit()
                return code
            except aiomysql.IntegrityError as e:
                if getattr(e, "args", [None])[0] == 1062:
                    continue
                raise
        raise RuntimeError("Konnte keinen eindeutigen Backup-Code erzeugen.")

    async def _fetch_backup(self, code: str) -> tuple[dict, dict]:
        async with self.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM backups WHERE code=%s", (code,))
            row = await cur.fetchone()
            if not row:
                raise commands.UserInputError("Backup nicht gefunden.")
        blob = row["data_blob"]
        buf = memoryview(blob)

        if buf[:4] == ZSTD_MAGIC:
            raw = zstd.ZstdDecompressor().decompress(buf)
        elif buf[:2] == b"\x1f\x8b":
            raw = gzip.decompress(buf)
        else:
            raw = blob

        return loads(raw), row

    async def _fetch_latest_code(self, guild_id: int) -> str | None:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT code FROM backups WHERE guild_id=%s ORDER BY created_at DESC LIMIT 1", (guild_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    # ---------- Export/Import (Datei <-> DB) ----------
    async def _export_backup_bytes(self, code: str, *, fmt: str = "zst") -> tuple[str, bytes]:
        """
        Exportiert einen bestehenden DB-Backup-Datensatz als Datei.
        WICHTIG: DB-Eintrag bleibt bestehen (kein Delete).
        Datei enthält Metadaten + payload; ganze Datei wird (wie in DB) komprimiert.
        """
        data, row = await self._fetch_backup(code)

        doc = {
            "format": "astra-backup",
            "format_version": 1,
            "backup_version": int(row["version"]),
            "code": row["code"],
            "guild_id": int(row["guild_id"]),
            "includes": row.get("includes") or compute_includes(data),
            "hash": row["hash"].hex() if isinstance(row["hash"], (bytes, bytearray)) else str(row["hash"]),
            "payload": data,
        }

        raw = dumps(doc)

        fmt_def = BACKUP_EXPORT_FORMATS.get(fmt)
        if not fmt_def:
            raise commands.UserInputError("Unbekanntes Export-Format.")

        out = fmt_def["compress"](raw)
        filename = f"astra-backup_{row['code']}_v{row['version']}.{fmt_def['ext']}"
        return filename, out

    def _try_decompress_any(self, data: bytes) -> list[bytes]:
        raws: list[bytes] = []
        buf = memoryview(data)

        # zstd (Magic Bytes)
        if buf[:4] == ZSTD_MAGIC:
            try:
                raws.append(zstd.ZstdDecompressor().decompress(buf))
            except Exception:
                pass

        # gzip (1F 8B)
        if buf[:2] == b"\x1f\x8b":
            try:
                raws.append(gzip.decompress(buf))
            except Exception:
                pass

        # plain
        raws.append(data)
        return raws

    async def _verify_and_fix_db_entry(self, code: str) -> None:
        """
        Prüft den DB-Datensatz auf Vollständigkeit/Konsistenz:
        - dekomprimiert data_blob -> payload
        - recompute includes, size_bytes, hash
        - korrigiert fehlende/falsche Werte per UPDATE
        """
        data, row = await self._fetch_backup(code)

        # payload (re-)serialisieren für Hash/Blob-Vergleich
        payload_raw = dumps(data)
        digest = blake128(payload_raw)
        size_bytes = int(row.get("size_bytes") or 0)
        includes = (row.get("includes") or compute_includes(data))

        blob_db: bytes = row["data_blob"]
        buf = memoryview(blob_db)

        if buf[:4] == ZSTD_MAGIC:
            blob_should = zstd.ZstdCompressor(level=12).compress(payload_raw)
        elif buf[:2] == b"\x1f\x8b":
            blob_should = gzip.compress(payload_raw)
        else:
            blob_should = gzip.compress(payload_raw)

        needs_update = False
        fields: dict[str, T.Any] = {}

        if size_bytes != len(row["data_blob"]):
            fields["size_bytes"] = len(row["data_blob"])
            needs_update = True

        # hash in DB kann bytes oder hex-string sein
        db_hash = row["hash"]
        db_hash_hex = db_hash.hex() if isinstance(db_hash, (bytes, bytearray)) else str(db_hash)
        if db_hash_hex.lower() != digest.hex():
            fields["hash"] = digest
            needs_update = True

        if not row.get("includes") or row.get("includes") != includes:
            fields["includes"] = includes
            needs_update = True

        # Wenn blob inhaltlich nicht passt (z. B. aus extern importiert ohne korrekte Kompression)
        if blob_db != blob_should:
            fields["data_blob"] = blob_should
            fields["size_bytes"] = len(blob_should)
            needs_update = True

        if needs_update:
            async with self.pool.acquire() as conn, conn.cursor() as cur:
                parts = ", ".join(f"{k}=%s" for k in fields)
                await cur.execute(f"UPDATE backups SET {parts} WHERE code=%s", (*fields.values(), code))
                await conn.commit()

    async def _import_backup_bytes(self, file_bytes: bytes, *, guild_id: int, overwrite: bool = False) -> str:
        """
        Importiert eine Backup-Datei (zstd/gzip/plain JSON/.txt) und schreibt/upsertet in DB.
        - Prüft/rekonstruiert alle Felder (includes, version, size, hash, blob)
        - 'overwrite=False': bei Code-Kollision wird ein neuer Code vergeben
        - 'overwrite=True' : vorhandener Code wird aktualisiert
        Rückgabe: effektiver Backup-Code in der DB.
        """
        # 1) Versuche dekomprimieren → JSON parsen
        raw_candidates: list[bytes] = []

        # zst / gz / weitere Formate aus BACKUP_EXPORT_FORMATS
        buf = memoryview(file_bytes)

        if buf[:4] == ZSTD_MAGIC:
            raw_candidates.append(zstd.ZstdDecompressor().decompress(buf))
        elif buf[:2] == b"\x1f\x8b":
            raw_candidates.append(gzip.decompress(buf))
        else:
            raw_candidates.append(file_bytes)

        # plain bytes als UTF-8 (json / txt)
        if not raw_candidates:
            try:
                raw_candidates.append(file_bytes)
            except Exception:
                pass

        doc = None
        last_err = None
        for raw in raw_candidates:
            try:
                # 1) direkt JSON
                doc = loads(raw)
                break
            except Exception as e_json:
                last_err = e_json
                # 2) .txt mit "payload=" herausparsen (Fallback)
                try:
                    text = raw.decode("utf-8", "ignore")
                    if "payload=" in text:
                        payload_str = text.split("payload=", 1)[1].strip()
                        # bis evtl. delimiter
                        for stop in ["\n---", "\n###", "\nEND", "\nEOF"]:
                            payload_str = payload_str.split(stop, 1)[0]
                        payload = loads(payload_str.encode())
                        # minimaler Container bauen
                        doc = {
                            "format": "astra-backup",
                            "format_version": 1,
                            "backup_version": BACKUP_VERSION,
                            "code": None,
                            "guild_id": guild_id,
                            "includes": compute_includes(payload),
                            "hash": blake128(dumps(payload)).hex(),
                            "payload": payload,
                        }
                        break
                except Exception as e_fallback:
                    last_err = e_fallback
                    continue

        if not isinstance(doc, dict):
            raise commands.UserInputError(
                f"Ungültige Backup-Datei (.txt/.json/.zst/.gz): {last_err or 'keine lesbaren Daten'}"
            )

        # 2) Validieren / Defaults setzen
        if doc.get("format") != "astra-backup":
            # Falls Nutzer rohen payload reinkopiert hat (ohne Header), akzeptieren
            if "roles" in doc or "channels" in doc:
                doc = {
                    "format": "astra-backup",
                    "format_version": 1,
                    "backup_version": int(doc.get("version") or BACKUP_VERSION),
                    "code": None,
                    "guild_id": guild_id,
                    "includes": compute_includes(doc),
                    "hash": blake128(dumps(doc)).hex(),
                    "payload": doc,
                }
            else:
                raise commands.UserInputError(
                    "Ungültiges Format. Erwartet 'astra-backup' oder rohen payload (roles/channels)."
                )

        payload = doc.get("payload")
        if not isinstance(payload, dict):
            raise commands.UserInputError("Fehlendes oder ungültiges 'payload' im Backup.")

        version = int(doc.get("backup_version") or BACKUP_VERSION)
        code_in_file = (doc.get("code") or "").strip() or gen_backup_code()

        # 3) Hash/Includes aus payload berechnen
        payload_raw = dumps(payload)
        digest = blake128(payload_raw)
        includes = compute_includes(payload)

        # 4) DB upsert (mit korrekter Kompression)
        blob = (
            zstd.ZstdCompressor(level=12).compress(payload_raw)
            if _HAS_ZSTD
            else gzip.compress(payload_raw)
        )  # type: ignore

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM backups WHERE code=%s", (code_in_file,))
            exists = await cur.fetchone()
            if exists and not overwrite:
                code = gen_backup_code()
            else:
                code = code_in_file

            if exists and overwrite:
                await cur.execute(
                    """
                    UPDATE backups
                    SET guild_id=%s,
                        includes=%s,
                        version=%s,
                        size_bytes=%s,
                        `hash`=%s,
                        data_blob=%s,
                        created_at=NOW()
                    WHERE code = %s
                    """,
                    (guild_id, includes, version, len(blob), digest, blob, code)
                )
            else:
                await cur.execute(
                    """
                    INSERT INTO backups (code, guild_id, includes, version, size_bytes, `hash`, data_blob)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (code, guild_id, includes, version, len(blob), digest, blob)
                )
            await conn.commit()

        # 5) Sicherheit: gleich verifizieren/ggf. korrigieren
        await self._verify_and_fix_db_entry(code)
        return code

    # ---------- Snapshot ----------
    async def _snapshot_guild(self, guild: discord.Guild) -> dict:

        roles = [{
            "name": r.name,
            "color": r.color.value,
            "permissions": r.permissions.value,
            "position": r.position,
            "hoist": r.hoist,
            "mentionable": r.mentionable
        } for r in sorted(guild.roles, key=lambda x: x.position)]

        def serialize_overwrites(channel):
            overwrites = []
            for target, po in channel.overwrites.items():
                allow, deny = po.pair()
                overwrites.append({
                    "target_name": target.name,
                    "target_type": "role" if isinstance(target, discord.Role) else "member",
                    "allow": allow.value,
                    "deny": deny.value
                })
            return overwrites

        categories = []
        uncategorized = []

        # Kategorien zuerst
        for cat in sorted(guild.categories, key=lambda x: x.position):

            cat_data = {
                "name": cat.name,
                "position": cat.position,
                "overwrites": serialize_overwrites(cat),
                "channels": []
            }

            for ch in sorted(cat.channels, key=lambda x: x.position):
                cat_data["channels"].append({
                    "type": int(ch.type.value),
                    "name": ch.name,
                    "topic": getattr(ch, "topic", None),
                    "position": ch.position,
                    "nsfw": getattr(ch, "nsfw", False),
                    "overwrites": serialize_overwrites(ch)
                })

            categories.append(cat_data)

        # Channels ohne Kategorie
        for ch in guild.channels:
            if ch.category is None and not isinstance(ch, discord.CategoryChannel):
                uncategorized.append({
                    "type": int(ch.type.value),
                    "name": ch.name,
                    "topic": getattr(ch, "topic", None),
                    "position": ch.position,
                    "nsfw": getattr(ch, "nsfw", False),
                    "overwrites": serialize_overwrites(ch)
                })

        return {
            "version": BACKUP_VERSION,
            "roles": roles,
            "categories": categories,
            "uncategorized": uncategorized
        }

    # ---------- Restore / Undo ----------
    def _build_overwrites(self, guild: discord.Guild, ow_data: list[dict]):
        overwrites: dict[discord.Role, discord.PermissionOverwrite] = {}
        for ow in (ow_data or []):
            if ow.get("target_type") == "role":
                role = discord.utils.get(guild.roles, name=ow.get("target_name"))
                if role:
                    overwrites[role] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(ow.get("allow", 0)),
                        discord.Permissions(ow.get("deny", 0))
                    )
        return overwrites

    async def _maybe_edit_progress_embed(self, job_id: int, *, running_status: str | None = None, force: bool = False):
        """Editiere das Fortschritts-Embed höchstens alle ~1.5s (oder sofort mit force=True)."""
        now = time.time()
        last = self._last_embed_edit.get(job_id, 0.0)
        if force or (now - last) >= 1.5:
            await self._edit_progress_embed(job_id, running_status=running_status)
            self._last_embed_edit[job_id] = now

    async def _restore_to_guild(self, guild: discord.Guild, data: dict, job_id: int):
        """Vollständiges Restore:
        - erstellt fehlende Objekte
        - repariert existierende Objekte
        - stellt Kategorien & Positionen exakt wieder her
        """

        created_ids = {"roles": [], "channels": []}
        roles_data = data.get("roles", []) or []

        # =====================================================
        # FORMAT ERKENNUNG
        # =====================================================
        if "categories" in data:
            categories_data = data.get("categories", []) or []
            uncategorized_data = data.get("uncategorized", []) or []
        else:
            channels_data = data.get("channels", []) or []
            categories_data = []
            uncategorized_data = []

            categories_map = {}
            for ch in channels_data:
                if ch["type"] == discord.ChannelType.category.value:
                    categories_map[ch["name"]] = {
                        "data": ch,
                        "channels": []
                    }

            for ch in channels_data:
                if ch["type"] != discord.ChannelType.category.value:
                    parent = ch.get("parent_name")
                    if parent and parent in categories_map:
                        categories_map[parent]["channels"].append(ch)
                    else:
                        uncategorized_data.append(ch)

            for name, bundle in categories_map.items():
                categories_data.append({
                    "name": name,
                    "position": bundle["data"].get("position", 0),
                    "overwrites": bundle["data"].get("overwrites", []),
                    "channels": bundle["channels"]
                })

        # =====================================================
        # VORZÄHLEN
        # =====================================================
        total = (
                len(roles_data)
                + len(categories_data)
                + sum(len(c.get("channels", [])) for c in categories_data)
                + len(uncategorized_data)
        )

        step = 0
        await self._update_job(job_id, step=0, total_steps=total)
        await self._maybe_edit_progress_embed(job_id, running_status="Starte Restore …", force=True)

        # =====================================================
        # 1️⃣ ROLLEN (Create + Repair)
        # =====================================================
        for r in roles_data:
            role = discord.utils.get(guild.roles, name=r["name"])

            try:
                if not role:
                    role = await guild.create_role(
                        name=r["name"],
                        permissions=discord.Permissions(r["permissions"]),
                        colour=discord.Colour(r["color"]),
                        hoist=r["hoist"],
                        mentionable=r["mentionable"],
                        reason="Astra Backup Restore"
                    )
                    created_ids["roles"].append(role.id)
                else:
                    await role.edit(
                        permissions=discord.Permissions(r["permissions"]),
                        colour=discord.Colour(r["color"]),
                        hoist=r["hoist"],
                        mentionable=r["mentionable"],
                        reason="Astra Backup Repair"
                    )
            except discord.Forbidden:
                pass

            step += 1
            await self._update_job(job_id, step=step)
            await self._maybe_edit_progress_embed(job_id, running_status="Synchronisiere Rollen …")
            await gentle_sleep()

        # =====================================================
        # 2️⃣ KATEGORIEN (Create + Repair)
        # =====================================================
        category_objects = {}

        for cat in categories_data:
            cat_obj = discord.utils.get(guild.categories, name=cat["name"])

            try:
                if not cat_obj:
                    cat_obj = await guild.create_category(
                        cat["name"],
                        overwrites=self._build_overwrites(guild, cat.get("overwrites", [])),
                        reason="Astra Backup Restore"
                    )
                    created_ids["channels"].append(cat_obj.id)
                else:
                    await cat_obj.edit(
                        overwrites=self._build_overwrites(guild, cat.get("overwrites", [])),
                        reason="Astra Backup Repair"
                    )

                category_objects[cat["name"]] = cat_obj

            except discord.Forbidden:
                pass

            step += 1
            await self._update_job(job_id, step=step)
            await self._maybe_edit_progress_embed(job_id, running_status="Synchronisiere Kategorien …")
            await gentle_sleep()

        # =====================================================
        # 3️⃣ CHANNELS INNERHALB KATEGORIEN (Create + Repair)
        # =====================================================
        for cat in categories_data:

            parent = category_objects.get(cat["name"])
            if not parent:
                continue

            for ch in cat.get("channels", []):

                ch_obj = discord.utils.get(guild.channels, name=ch["name"])
                overwrites = self._build_overwrites(guild, ch.get("overwrites", []))
                ctype = discord.ChannelType(ch["type"])

                try:
                    if not ch_obj:

                        if ctype in (discord.ChannelType.text, discord.ChannelType.news):
                            ch_obj = await guild.create_text_channel(
                                name=ch["name"],
                                topic=ch.get("topic"),
                                nsfw=ch.get("nsfw", False),
                                category=parent,
                                overwrites=overwrites,
                                reason="Astra Backup Restore"
                            )

                        elif ctype is discord.ChannelType.voice:
                            ch_obj = await guild.create_voice_channel(
                                name=ch["name"],
                                category=parent,
                                overwrites=overwrites,
                                reason="Astra Backup Restore"
                            )

                        else:
                            continue

                        created_ids["channels"].append(ch_obj.id)

                    else:
                        await ch_obj.edit(
                            category=parent,
                            topic=ch.get("topic") if hasattr(ch_obj, "topic") else None,
                            nsfw=ch.get("nsfw", False) if hasattr(ch_obj, "nsfw") else None,
                            overwrites=overwrites,
                            reason="Astra Backup Repair"
                        )

                except discord.Forbidden:
                    pass

                step += 1
                await self._update_job(job_id, step=step)
                await self._maybe_edit_progress_embed(job_id, running_status="Synchronisiere Channels …")
                await gentle_sleep()

        # =====================================================
        # 4️⃣ UNCATEGORIZED CHANNELS (Repair included)
        # =====================================================
        for ch in uncategorized_data:

            ch_obj = discord.utils.get(guild.channels, name=ch["name"])
            overwrites = self._build_overwrites(guild, ch.get("overwrites", []))
            ctype = discord.ChannelType(ch["type"])

            try:
                if not ch_obj:

                    if ctype in (discord.ChannelType.text, discord.ChannelType.news):
                        ch_obj = await guild.create_text_channel(
                            name=ch["name"],
                            topic=ch.get("topic"),
                            nsfw=ch.get("nsfw", False),
                            overwrites=overwrites,
                            reason="Astra Backup Restore"
                        )

                    elif ctype is discord.ChannelType.voice:
                        ch_obj = await guild.create_voice_channel(
                            name=ch["name"],
                            overwrites=overwrites,
                            reason="Astra Backup Restore"
                        )
                    else:
                        continue

                    created_ids["channels"].append(ch_obj.id)

                else:
                    await ch_obj.edit(
                        category=None,
                        topic=ch.get("topic") if hasattr(ch_obj, "topic") else None,
                        nsfw=ch.get("nsfw", False) if hasattr(ch_obj, "nsfw") else None,
                        overwrites=overwrites,
                        reason="Astra Backup Repair"
                    )

            except discord.Forbidden:
                pass

            step += 1
            await self._update_job(job_id, step=step)
            await self._maybe_edit_progress_embed(job_id, running_status="Synchronisiere Uncategorized …")
            await gentle_sleep()

        # =====================================================
        # 🔥 POSITION RESTORE
        # =====================================================
        await self._maybe_edit_progress_embed(job_id, running_status="Stelle Reihenfolge wieder her …", force=True)

        # Rollen
        for idx, r in enumerate(sorted(roles_data, key=lambda x: x.get("position", 0))):
            role = discord.utils.get(guild.roles, name=r["name"])
            if role:
                try:
                    await role.edit(position=idx)
                except Exception:
                    pass
                await gentle_sleep()

        # Kategorien
        for idx, cat in enumerate(sorted(categories_data, key=lambda x: x.get("position", 0))):
            cat_obj = discord.utils.get(guild.categories, name=cat["name"])
            if cat_obj:
                try:
                    await cat_obj.edit(position=idx)
                except Exception:
                    pass
                await gentle_sleep()

        # Channels innerhalb Kategorien
        for cat in categories_data:
            parent = discord.utils.get(guild.categories, name=cat["name"])
            if not parent:
                continue

            for idx, ch in enumerate(sorted(cat.get("channels", []), key=lambda x: x.get("position", 0))):
                ch_obj = discord.utils.get(parent.channels, name=ch["name"])
                if ch_obj:
                    try:
                        await ch_obj.edit(position=idx)
                    except Exception:
                        pass
                    await gentle_sleep()

        await self._maybe_edit_progress_embed(job_id, running_status="Abschließen …", force=True)
        return created_ids

    async def _undo_restore(self, guild: discord.Guild, job: dict):
        created_objs = loads(job["created_objects"].encode()) if job.get("created_objects") else {}
        chan_ids = list(reversed(created_objs.get("channels", [])))
        role_ids = created_objs.get("roles", [])

        total = len(chan_ids) + len(role_ids)
        step = 0
        await self._update_job(job["job_id"], step=step, total_steps=total)
        await self._maybe_edit_progress_embed(job["job_id"], running_status="Starte Undo …", force=True)

        # Channels
        for cid in chan_ids:
            ch = guild.get_channel(cid)
            if ch:
                try:
                    await ch.delete(reason="Astra Backup Undo")
                except discord.Forbidden:
                    pass
            step += 1
            await self._update_job(job["job_id"], step=step)
            await self._maybe_edit_progress_embed(job["job_id"], running_status="Lösche Channels …")
            await gentle_sleep()

        # Rollen
        for rid in role_ids:
            role = guild.get_role(rid)
            if role:
                try:
                    await role.delete(reason="Astra Backup Undo")
                except discord.Forbidden:
                    pass
            step += 1
            await self._update_job(job["job_id"], step=step)
            await self._maybe_edit_progress_embed(job["job_id"], running_status="Lösche Rollen …")
            await gentle_sleep()

        await self._maybe_edit_progress_embed(job["job_id"], running_status="Abschließen …", force=True)

    # ---------- Embed Updater ----------
    async def _edit_progress_embed(self, job_id: int, running_status: str | None = None,
                                   final_status: str | None = None, color: discord.Color | None = None):
        job = await self._fetch_job(job_id)
        if not job:
            return
        ch_id = job.get("status_channel_id")
        msg_id = job.get("status_message_id")
        if not ch_id or not msg_id:
            return
        channel = self.bot.get_channel(ch_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel,
                                    discord.StageChannel, discord.ForumChannel)):
            return
        try:
            msg = await channel.fetch_message(msg_id)
        except Exception:
            return

        status_text = final_status or running_status or job.get("status", "running")
        embed = build_progress_embed(
            title=f"Astra • Backup-Job • #{job_id} ({job.get('type')})",
            step=job.get("step", 0),
            total=job.get("total_steps", 0),
            status=status_text,
            color=color or discord.Colour.blue(),
            error=job.get("last_error")
        )
        try:
            await msg.edit(embed=embed)
        except Exception:
            pass


# ==========================================================================================
# Slash-Command Gruppe als app_commands.Group (guild-only), außerhalb der Cog – Astra Style
# ==========================================================================================
@app_commands.guild_only()
class Backup(app_commands.Group):
    """Slash-Gruppe für Astra Backup (nur in Guilds)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__(name="backup", description="Astra Backup & Restore")

    def _cog(self) -> BackupCog:
        cog = self.bot.get_cog("BackupCog")
        if cog is None:
            raise RuntimeError("BackupCog ist nicht geladen.")
        return cog

    @app_commands.command(name="erstellen", description="Erstellt ein Server-Backup.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_create(self, interaction: discord.Interaction):
        cog = self._cog()
        await interaction.response.defer(ephemeral=True)
        payload = await cog._snapshot_guild(interaction.guild)
        code = await cog._store_backup(interaction.guild_id, payload)
        emb = discord.Embed(
            title="Backup erstellt",
            description=f"<:Astra_accept:1141303821176422460> **Code:** `{code}`\nEnthält Rollen, Kategorien, Channels & Overwrites.",
            color=discord.Colour.blue(),
        )
        await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="liste", description="Backups – eine Nachricht, schön & ausführlich")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_list(self, interaction: discord.Interaction):
        cog = self._cog()

        async with cog.pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """
                SELECT code, created_at, includes, version, size_bytes, data_blob
                FROM backups
                WHERE guild_id = %s
                ORDER BY created_at DESC
                """,
                (interaction.guild_id,)
            )
            rows = await cur.fetchall()

        if not rows:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Es sind keine Backups vorhanden.",
                ephemeral=True
            )
            return

        entries: list[dict] = []

        for r in rows:
            blob = r["data_blob"]
            buf = memoryview(blob)

            if buf[:4] == ZSTD_MAGIC:
                raw = zstd.ZstdDecompressor().decompress(buf)
            elif buf[:2] == b"\x1f\x8b":
                raw = gzip.decompress(buf)
            else:
                raw = blob

            data = loads(raw)

            roles = data.get("roles", []) or []

            # =====================================================
            # FORMAT FIX
            # =====================================================
            if "categories" in data:
                chans = []

                for cat in data.get("categories", []):
                    # Kategorie selbst
                    chans.append({
                        "type": discord.ChannelType.category.value,
                        "name": cat.get("name")
                    })

                    # Unterchannels
                    for ch in cat.get("channels", []):
                        ch_copy = ch.copy()
                        ch_copy["parent_name"] = cat.get("name")
                        chans.append(ch_copy)

                # Uncategorized
                for ch in data.get("uncategorized", []):
                    ch_copy = ch.copy()
                    ch_copy["parent_name"] = None
                    chans.append(ch_copy)

            else:
                chans = data.get("channels", []) or []

            # =====================================================
            # ANALYSE
            # =====================================================
            role_names = sorted(
                [x["name"] for x in roles if x.get("name") and x["name"] != "@everyone"],
                key=lambda s: s.casefold()
            )

            categories = [c for c in chans if c.get("type") == discord.ChannelType.category.value]
            text = [c for c in chans if
                    c.get("type") in (discord.ChannelType.text.value, discord.ChannelType.news.value)]
            voice = [c for c in chans if c.get("type") == discord.ChannelType.voice.value]
            stage = [c for c in chans if c.get("type") == discord.ChannelType.stage_voice.value]
            forum = [c for c in chans if c.get("type") == discord.ChannelType.forum.value]
            news = [c for c in chans if c.get("type") == discord.ChannelType.news.value]

            category_tree = build_category_tree_block(interaction.guild, chans)

            entries.append({
                "code": r["code"],
                "created_at": r["created_at"],
                "version": r["version"],
                "size": human_bytes(r["size_bytes"]) if isinstance(r["size_bytes"], (int, float)) else "?",
                "roles_count": len(role_names),
                "categories_count": len(categories),
                "category_tree": category_tree,
                "channels_total": len(chans) - len(categories),
                "text_count": len(text),
                "voice_count": len(voice),
                "stage_count": len(stage),
                "forum_count": len(forum),
                "news_count": len(news),
                "overwrites_total": sum(len(c.get("overwrites") or []) for c in chans),
                "role_names": role_names,
                "text_names": sorted([c["name"] for c in text if c.get("name")], key=lambda s: s.casefold()),
                "voice_names": sorted([c["name"] for c in voice if c.get("name")], key=lambda s: s.casefold()),
            })

        total = len(entries)

        def build_embed(entry: dict, idx: int, total_count: int) -> discord.Embed:
            guild = interaction.guild
            ts = int(entry["created_at"].timestamp())

            head = (
                f"<:Astra_info:1141303860556738620> **`{entry['code']}`**  •  v{entry['version']}  •  {entry['size']}\n"
                f"<:Astra_calender:1141303828625489940> <t:{ts}:f> • <t:{ts}:R>\n"
                f"<:Astra_file2:1141303839543279666> Insgesamt **{total_count}** Backups (neu → alt)."
            )

            e = discord.Embed(
                title="Astra • Backups (Detailansicht)",
                description=head,
                color=discord.Colour.blue()
            )

            row1 = " | ".join([
                f"<:Astra_users:1141303946602872872> Rollen **{entry['roles_count']}**",
                f"<:Astra_file2:1141303839543279666> Kategorien **{entry['categories_count']}**",
                f"<:Astra_messages:1141303867850641488> Text **{entry['text_count']}**",
                f"<:Astra_hear:1141303854881833081> Voice **{entry['voice_count']}**",
            ])

            row2 = " | ".join([
                f"<:Astra_news:1141303885533827072> News **{entry['news_count']}**",
                f"<:Astra_mic_on:1141303873294844005> Stage **{entry['stage_count']}**",
                f"<:Astra_stift:1141825585836998716> Forum **{entry['forum_count']}**",
                f"<:Astra_locked:1141824745243942912> Berechtigungen **{entry['overwrites_total']}**",
            ])

            e.add_field(name="Inhalt (Zähler)", value=f"{row1}\n{row2}", inline=False)

            e.add_field(
                name=f"Rollen ({entry['roles_count']})",
                value=build_vertical_list_role_mentions(guild, entry["role_names"]),
                inline=False
            )

            e.add_field(
                name=f"Kategorien ({entry['categories_count']}) & Kanäle",
                value=entry["category_tree"],
                inline=False
            )

            e.add_field(
                name=f"Textkanäle ({entry['text_count']})",
                value=build_vertical_list_mentions(
                    guild,
                    entry["text_names"],
                    prefix_channel_type=discord.ChannelType.text.value
                ),
                inline=False
            )

            e.add_field(
                name=f"Voicekanäle ({entry['voice_count']})",
                value=build_vertical_list_mentions(
                    guild,
                    entry["voice_names"],
                    prefix_channel_type=discord.ChannelType.voice.value
                ),
                inline=False
            )

            e.set_footer(text=f"Seite {idx + 1}/{total_count}")
            return e

        view = BackupListView(entries, build_embed)
        await interaction.response.send_message(
            embed=build_embed(entries[0], 0, total),
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="laden", description="Stellt ein Backup mithilfe eines Codes wieder her.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(code="Der Backup-Code, der wiederhergestellt werden soll.")
    async def backup_load(self, interaction: discord.Interaction, code: str):

        cog = self._cog()
        try:
            await cog._fetch_backup(code)
        except Exception as e:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Der Backup-Code war ungültig.", ephemeral=True)
            return

        start_embed = build_progress_embed(
            title="Astra • Backup-Wiederherstellung startet …",
            step=0, total=0, status="Wird in die Warteschlange gestellt …",
            color=discord.Colour.blue()
        )
        await interaction.response.send_message(embed=start_embed, ephemeral=False)
        msg = await interaction.original_response()

        job_id = await cog._queue_job(
            interaction.guild_id, "restore", code,
            status_channel_id=msg.channel.id, status_message_id=msg.id
        )
        await cog._edit_progress_embed(job_id, running_status="In Warteschlange …")
        await interaction.followup.send(
            f"<:Astra_info:1141303860556738620> Restore-Job gestartet (ID **{job_id}**). Fortschritt siehe oben oder mit `/backup status`.",
            ephemeral=True
        )

    @app_commands.command(name="zurücksetzen", description="Stellt den Stand vor der letzten Wiederherstellung wieder her.")
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_undo(self, interaction: discord.Interaction):
        cog = self._cog()
        last_restore = await cog._fetch_last_restore_job(interaction.guild_id)
        if not last_restore:
            await interaction.response.send_message(
                embed=discord.Embed(title="📭 Kein Restore-Job gefunden", color=discord.Colour.blue()),
                ephemeral=True
            )
            return

        start_embed = build_progress_embed(
            title=f"Astra • Rückgängig für Restore-Job #{last_restore['job_id']}",
            step=0, total=0, status="Lösche hinzugefügte Objekte …",
            color=discord.Colour.blue()
        )
        await interaction.response.send_message(embed=start_embed, ephemeral=False)
        msg = await interaction.original_response()

        created_objects = last_restore.get("created_objects")
        undo_job_id = await cog._queue_job(
            interaction.guild_id, "undo", last_restore.get("code"),
            status_channel_id=msg.channel.id, status_message_id=msg.id
        )
        if created_objects:
            await cog._update_job(undo_job_id, created_objects=created_objects)

        job_row = await cog._fetch_job(undo_job_id)
        asyncio.create_task(cog._run_job(job_row))

        await interaction.followup.send(
            f"<:Astra_info:1141303860556738620> Undo-Job gestartet (ID **{undo_job_id}**). Fortschritt siehe oben.",
            ephemeral=True
        )

    @app_commands.command(name="status", description="Zeigt den Status des letzten Backup- oder Wiederherstellungsvorgangs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def backup_status(self, interaction: discord.Interaction):
        cog = self._cog()
        job = await cog._fetch_last_job_for_guild(interaction.guild_id)
        if not job:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Es gibt keine Aktiven Backup-Jobs.", ephemeral=True)
            return
        emb = build_progress_embed(
            title=f"Astra • Letzter Job • #{job['job_id']} ({job['type']})",
            step=job.get("step", 0), total=job.get("total_steps", 0),
            status=job.get("status"), color=discord.Colour.blue(),
            error=job.get("last_error")
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="löschen", description="Lösche ältere Backups.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(code="Der Backup-Code, der gelöscht werden soll.")
    async def backup_delete(self, interaction: discord.Interaction, code: str):
        cog = self._cog()

        async with cog.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM backups WHERE code=%s LIMIT 1", (code,))
            exists = await cur.fetchone()

        if not exists:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Der Backup-Code war ungültig.", ephemeral=True)
            return

        async with cog.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM backup_jobs WHERE code=%s AND status='running'",
                (code,)
            )
            (running_count,) = await cur.fetchone()

            await cur.execute(
                "SELECT COUNT(*) FROM backup_jobs WHERE code=%s AND status!='running'",
                (code,)
            )
            (deletable_jobs,) = await cur.fetchone()

            await cur.execute(
                "DELETE FROM backup_jobs WHERE code=%s AND status!='running'",
                (code,)
            )

            await cur.execute("DELETE FROM backups WHERE code=%s", (code,))
            await conn.commit()

        desc = [
            f"<:Astra_file1:1141303837181886494> Backup `{code}` gelöscht.",
            f"<:Astra_stift:1141825585836998716> Entfernte Jobs (pending/done/error): **{deletable_jobs}**"
        ]
        if running_count:
            desc.append(f"<:Astra_info:1141303860556738620> Laufende Jobs zum Code: **{running_count}** (nicht gelöscht)")

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Bereinigung abgeschlossen",
                description="\n".join(desc),
                color=discord.Colour.blue()
            ),
            ephemeral=True
        )

    @app_commands.command(name="exportieren", description="Exportiert ein Backup als Datei (.zst.json oder .gz.json).")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(code="Backup-Code, der exportiert werden soll.")
    @app_commands.choices(
        dateiformat=[
            app_commands.Choice(name="zst (empfohlen)", value="zst"),
            app_commands.Choice(name="gz", value="gz"),
            app_commands.Choice(name="json (unkomprimiert)", value="json"),
        ]
    )
    async def backup_export(self, interaction: discord.Interaction, code: str, dateiformat: str = "gz"):
        cog = self._cog()
        try:
            filename, file_bytes = await cog._export_backup_bytes(code, fmt=dateiformat)
        except commands.UserInputError:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Ungültiger Backup-Code.",
                                                    ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"<:Astra_x:1141303954555289600> Export-Fehler: {e}",
                                                    ephemeral=True)
            return

        file = discord.File(fp=io.BytesIO(file_bytes), filename=filename)  # FIXED
        emb = discord.Embed(
            title="Backup exportiert",
            description=(
                f"**Code:** `{code}`\n"
                f"Der Datensatz bleibt **in der Datenbank erhalten**. "
                f"Du kannst ihn separat mit `/backup delete` entfernen."
            ),
            color=discord.Colour.blue()
        )
        await interaction.response.send_message(embed=emb, file=file, ephemeral=True)

    @app_commands.command(name="importieren", description="Importiert ein Backup aus einer Datei (.txt/.json/.zst.json/.gz.json) in die DB.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(file="Die Export-Datei (oder .txt mit JSON/Payload)", overwrite="Vorhandenen Code überschreiben?")
    async def backup_import(self, interaction: discord.Interaction, file: discord.Attachment, overwrite: bool = False):
        cog = self._cog()
        await interaction.response.defer(ephemeral=True)

        # Datei laden
        try:
            file_bytes = await file.read()
        except Exception as e:
            await interaction.followup.send(f"<:Astra_x:1141303954555289600> Konnte Datei nicht lesen: {e}", ephemeral=True)
            return

        try:
            code = await cog._import_backup_bytes(file_bytes, guild_id=interaction.guild_id, overwrite=overwrite)
            await cog._verify_and_fix_db_entry(code)
        except commands.UserInputError as ue:
            await interaction.followup.send(f"<:Astra_x:1141303954555289600> {ue}", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"<:Astra_x:1141303954555289600> Import-Fehler: {e}", ephemeral=True)
            return

        # Success
        emb = discord.Embed(
            title="Backup importiert",
            description=(
                f"**Code:** `{code}`\n"
                f"Eintrag wurde in der **DB angelegt/aktualisiert** und ist damit lösch-/wiederherstellbar.\n"
                f"→ Du kannst es jetzt z. B. mit `/backup load code:{code}` laden."
            ),
            color=discord.Colour.blue()
        )
        await interaction.followup.send(embed=emb, ephemeral=True)



# -------------- setup: Cog + Group im Tree registrieren --------------
async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
    bot.tree.add_command(Backup(bot))
