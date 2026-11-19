"""
Restore missing Ticket Panel Message IDs (panelMsgID) for existing panels.

Usage:
  - Dry run (default):
      python scripts/restore_ticket_panel_message_ids.py --dry-run

  - Apply updates (write panelMsgID when a unique match was found):
      python scripts/restore_ticket_panel_message_ids.py --apply

Environment (reads like the internal API/Bot):
  - MySQL: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
  - Discord: DISCORD_TOKEN (or ASTRA_BOT_TOKEN)

Safety constraints:
  - Never sends/edits/deletes Discord messages.
  - Only updates ticketsystem.panelMsgID when a single, unambiguous match is found and
    only if the column exists and the value is currently NULL/not set.
  - No other database fields are modified.

Classification per panel row:
  - MATCH_FOUND: exactly one message matched and eligible for update
  - ALREADY_SAVED: panelMsgID is already stored (script does not overwrite)
  - MULTIPLE_MATCHES: more than one plausible message – no write
  - NO_MATCH: no plausible message found
  - MISSING_PERMISSIONS: cannot access channel history
  - GUILD_NOT_FOUND: bot cannot access the guild
  - INVALID_CHANNEL: channel not found or wrong type
  - ERROR: technical error
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
from dataclasses import dataclass
import hashlib
import uuid
import time
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

import aiomysql
import discord
from dotenv import load_dotenv


LOGGER = logging.getLogger("astra.restore_panel_msgid")

PANEL_BUTTON_CUSTOM_ID = "ticket_panel:open"
PANEL_FOOTER_TEXT = "Klicke auf den Button, um ein Ticket zu erstellen!"


@dataclass
class PanelRow:
    guild_id: int
    channel_id: int
    thema: str
    description: str
    role_id: Optional[int]
    category_id: Optional[int]
    panel_msg_id: Optional[int]
    panel_key: Optional[str] = None


@dataclass
class MatchResult:
    guild_id: int
    channel_id: int
    thema: str
    status: str
    message_id: Optional[int] = None
    reason: Optional[str] = None
    candidates: Optional[int] = None
    action: Optional[str] = None
    details: Optional[dict] = None
    panel_key: Optional[str] = None
    key_status: Optional[str] = None


class DB:
    def __init__(self, pool: aiomysql.Pool):
        self.pool = pool

    async def panelmsgid_column_exists(self) -> bool:
        # Explicit check via information_schema to avoid broad exception fallbacks
        q = (
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ticketsystem' AND COLUMN_NAME = 'panelMsgID'"
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q)
                row = await cur.fetchone()
                return bool(row)

    async def fetch_panels(self) -> List[PanelRow]:
        # Fetch all panels for which we may need to restore panelMsgID/description/panel_key
        # Detect column presence first to avoid catching unrelated SQL exceptions.
        items: List[PanelRow] = []
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Decide query by checking column existence
                await cur.execute(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ticketsystem'"
                )
                cols = [r[0] for r in await cur.fetchall()]
                has_msg_id = "panelMsgID" in cols
                has_desc = "description" in cols
                has_key = "panel_key" in cols

                q_cols = ["guildID", "channelID", "thema"]
                if has_desc: q_cols.append("description")
                if has_msg_id: q_cols.append("panelMsgID")
                if has_key: q_cols.append("panel_key")
                q_cols.extend(["roleID", "categoryID"])

                q = f"SELECT {', '.join(q_cols)} FROM ticketsystem"
                await cur.execute(q)
                rows = await cur.fetchall()
                
                # Mapping helper
                col_map = {name: i for i, name in enumerate(q_cols)}

                for r in rows:
                    items.append(
                        PanelRow(
                            guild_id=int(r[col_map["guildID"]]),
                            channel_id=int(r[col_map["channelID"]]),
                            thema=str(r[col_map["thema"]] or ""),
                            description=str(r[col_map[ "description"]] if has_desc else ""),
                            role_id=int(r[col_map["roleID"]]) if r[col_map["roleID"]] else None,
                            category_id=int(r[col_map["categoryID"]]) if r[col_map["categoryID"]] else None,
                            panel_msg_id=int(r[col_map["panelMsgID"]]) if has_msg_id and r[col_map["panelMsgID"]] else None,
                            panel_key=str(r[col_map["panel_key"]]) if has_key and r[col_map["panel_key"]] else None,
                        )
                    )
        return items

    async def update_panel_msg_id(self, guild_id: int, channel_id: int, message_id: int,
                                  *, role_id: Optional[int], category_id: Optional[int], thema: str, description: str) -> int:
        """Single-row update helper WITHOUT committing.

        Returns the number of affected rows (should be exactly 1 for a safe update).
        Transaction control (commit/rollback) must be handled by the caller.
        """
        q = (
            "UPDATE ticketsystem "
            "SET panelMsgID=%s, description=%s "
            "WHERE guildID=%s AND channelID=%s AND "
            "((roleID IS NULL AND %s IS NULL) OR roleID=%s) AND "
            "((categoryID IS NULL AND %s IS NULL) OR categoryID=%s) AND "
            "(thema <=> %s)"
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q, (
                    int(message_id), description, int(guild_id), int(channel_id),
                    role_id, role_id, category_id, category_id, thema
                ))
                return cur.rowcount

    async def prevalidate_unique_selectors(self, items: List[Tuple[int, int, Optional[int], Optional[int], str]] ) -> Tuple[bool, List[str]]:
        """Prevalidate that each selector matches exactly one row with empty panelMsgID.

        items: list of tuples (guild_id, channel_id, role_id, category_id, thema)
        Returns (ok, errors)
        """
        sel_q = (
            "SELECT COUNT(*) FROM ticketsystem "
            "WHERE guildID=%s AND channelID=%s AND "
            "((roleID IS NULL AND %s IS NULL) OR roleID=%s) AND "
            "((categoryID IS NULL AND %s IS NULL) OR categoryID=%s) AND "
            "(thema <=> %s)"
        )
        errors: List[str] = []
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for (g, ch, rid, cid, thema) in items:
                    await cur.execute(sel_q, (int(g), int(ch), rid, rid, cid, cid, thema))
                    row = await cur.fetchone()
                    cnt = int(row[0]) if row else 0
                    if cnt != 1:
                        errors.append(f"Selector not unique or missing (count={cnt}) for guild={g} channel={ch} thema={thema}")
        return (len(errors) == 0), errors

    async def apply_panel_updates_batch(self, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply all updates (msgID, description, panel_key) in a single transaction.
        
        updates: list of dicts with keys: guild_id, channel_id, role_id, category_id, thema, 
                 message_id (optional), description (optional), panel_key (optional)
        """
        result: Dict[str, Any] = {
            "planned": len(updates),
            "attempted": 0,
            "committed": 0,
            "applied": 0,
            "rolled_back": False,
            "errors": [],
        }
        if not updates:
            return result

        q_select_for_update = (
            "SELECT guildID, channelID, roleID, categoryID, thema FROM ticketsystem "
            "WHERE guildID=%s AND channelID=%s AND "
            "((roleID IS NULL AND %s IS NULL) OR roleID=%s) AND "
            "((categoryID IS NULL AND %s IS NULL) OR categoryID=%s) AND "
            "(thema <=> %s) "
            "FOR UPDATE"
        )

        async with self.pool.acquire() as conn:
            try:
                await conn.begin()
                async with conn.cursor() as cur:
                    for u in updates:
                        g, ch, rid, cid, th = u["guild_id"], u["channel_id"], u["role_id"], u["category_id"], u["thema"]
                        
                        # 1) Lock row
                        await cur.execute(q_select_for_update, (int(g), int(ch), rid, rid, cid, cid, th))
                        rows = await cur.fetchall()
                        if len(rows) != 1:
                            raise RuntimeError(f"Selector not unique for guild={g} channel={ch} thema={th}")

                        # 2) Build UPDATE dynamically based on what we want to change
                        upd_fields = []
                        upd_vals = []
                        if "message_id" in u:
                            upd_fields.append("panelMsgID=%s")
                            upd_vals.append(int(u["message_id"]))
                        if "description" in u:
                            upd_fields.append("description=%s")
                            upd_vals.append(u["description"])
                        if "panel_key" in u:
                            upd_fields.append("panel_key=%s")
                            upd_vals.append(u["panel_key"])

                        if not upd_fields:
                            continue

                        upd_q = f"UPDATE ticketsystem SET {', '.join(upd_fields)} WHERE guildID=%s AND channelID=%s AND ((roleID IS NULL AND %s IS NULL) OR roleID=%s) AND ((categoryID IS NULL AND %s IS NULL) OR categoryID=%s) AND (thema <=> %s)"
                        upd_vals.extend([int(g), int(ch), rid, rid, cid, cid, th])
                        
                        await cur.execute(upd_q, tuple(upd_vals))
                        result["attempted"] += 1
                        if cur.rowcount != 1:
                            raise RuntimeError(f"Unsafe update for guild={g} channel={ch} thema={th}")

                await conn.commit()
                result["committed"] = result["attempted"]
                result["applied"] = result["committed"]
            except Exception as e:
                result["errors"].append(str(e))
                result["rolled_back"] = True
                await conn.rollback()
                result["committed"] = 0
                result["applied"] = 0
            return result

    async def fetch_tickets_to_map(self) -> List[Dict[str, Any]]:
        """Holt alle Tickets aus ticketsystem_channels, die noch keinen panel_key haben."""
        q = "SELECT guildID, channelID, opened, msgID FROM ticketsystem_channels WHERE panel_key IS NULL OR panel_key = ''"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q)
                rows = await cur.fetchall()
                return [{"guild_id": r[0], "channel_id": r[1], "opener_id": r[2], "msg_id": r[3]} for r in rows]

    async def apply_ticket_mapping(self, mappings: List[Tuple[str, int]]) -> Dict[str, Any]:
        """Ordnet Tickets einem panel_key zu. mappings: list of (panel_key, channel_id)"""
        result = {"planned": len(mappings), "applied": 0, "errors": []}
        if not mappings: return result
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for key, ch_id in mappings:
                    try:
                        await cur.execute("UPDATE ticketsystem_channels SET panel_key=%s WHERE channelID=%s", (key, ch_id))
                        result["applied"] += cur.rowcount
                    except Exception as e:
                        result["errors"].append(f"Ticket {ch_id} failed: {e}")
            await conn.commit()
        return result

    async def fetch_autoclose_states_to_map(self) -> List[Dict[str, Any]]:
        """Holt alle Autoclose-States, die noch keinen panel_key haben."""
        q = "SELECT channelID FROM ticket_autoclose_state WHERE panel_key IS NULL OR panel_key = ''"
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(q)
                rows = await cur.fetchall()
                return [{"channel_id": r[0]} for r in rows]

    async def apply_autoclose_mapping(self, mappings: List[Tuple[str, int]]) -> Dict[str, Any]:
        """Ordnet Autoclose-States einem panel_key zu."""
        result = {"planned": len(mappings), "applied": 0, "errors": []}
        if not mappings: return result
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for key, ch_id in mappings:
                    try:
                        await cur.execute("UPDATE ticket_autoclose_state SET panel_key=%s WHERE channelID=%s", (key, ch_id))
                        result["applied"] += cur.rowcount
                    except Exception as e:
                        result["errors"].append(f"State {ch_id} failed: {e}")
            await conn.commit()
        return result

    async def fetch_logs_to_map(self) -> List[Dict[str, Any]]:
        """Holt alle Log-Konfigurationen, die noch keinen panel_key haben (für Migration auf panel_key=NULL=serverweit)."""
        # Wir betrachten hier nur Datensätze in ticketlog. 
        # Da ticketlog bisher nur guildID/channelID hatte, ist alles "serverweit" (panel_key=NULL).
        # Falls wir aber panelbezogene Logs hätten, müssten wir sie hier finden.
        return []

    async def apply_log_mapping(self, mappings: List[Tuple[str, int, int]]) -> Dict[str, Any]:
        """Ordnet Log-Konfigurationen einem panel_key zu."""
        return {"planned": 0, "applied": 0, "errors": []}


class PanelScanner:
    def __init__(self, client: discord.Client):
        self.client = client

    async def _resolve_guild(self, guild_id: int) -> Tuple[Optional[discord.Guild], Optional[Dict[str, Any]]]:
        """Versucht, die Guild aufzulösen. Liefert (guild, error_info).

        error_info enthält bei Fehlern folgende Felder:
          - type: Exception-Klassenname
          - status: Discord-HTTP-Status (falls vorhanden), sonst None
          - message: Fehlermeldung/Text
        """
        guild = self.client.get_guild(int(guild_id))
        if guild is not None:
            return guild, None
        # Versuch eines Live-Fetch (sparsam, nur einmal pro Gruppe sinnvoll)
        try:
            guild = await self.client.fetch_guild(int(guild_id))  # type: ignore[attr-defined]
            return guild, None  # type: ignore[return-value]
        except discord.Forbidden as e:
            return None, {"type": type(e).__name__, "status": getattr(e, "status", None), "message": str(getattr(e, "text", None) or e)}
        except discord.NotFound as e:
            return None, {"type": type(e).__name__, "status": getattr(e, "status", None), "message": str(getattr(e, "text", None) or e)}
        except discord.HTTPException as e:
            return None, {"type": type(e).__name__, "status": getattr(e, "status", None), "message": str(getattr(e, "text", None) or e)}
        except asyncio.TimeoutError as e:
            return None, {"type": type(e).__name__, "status": None, "message": str(e)}
        except Exception as e:
            return None, {"type": type(e).__name__, "status": None, "message": str(e)}

    async def scan_channel_messages(self, guild: discord.Guild, channel_id: int, *,
                                    max_messages: int = 2000) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Liest die History (einmal) und filtert nur potenzielle Panel-Messages (Autor=Bot, Embed, Button-ID, Footer).
        Rückgabe ist eine Liste vorbereiteter Message-Daten (inkl. Titeltext/Kriterien), die später
        für unterschiedliche Panel-Themen innerhalb dieses Channels erneut bewertet werden können.
        """
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            try:
                channel = await guild.fetch_channel(int(channel_id))  # type: ignore[assignment]
            except discord.Forbidden:
                raise PermissionError("Missing permissions to fetch channel")
            except discord.NotFound:
                return [], {"channel_fetch": "not_found"}
            except discord.HTTPException:
                return [], {"channel_fetch": "http_error"}
        if not isinstance(channel, discord.TextChannel):
            return [], {"channel_type": str(type(channel))}

        me = guild.me or await guild.fetch_member(self.client.user.id)  # type: ignore
        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.read_message_history:
            raise PermissionError("Missing permissions to read history")

        prefiltered: List[Dict[str, Any]] = []
        scanned = 0
        newest_id: Optional[int] = None
        oldest_id: Optional[int] = None

        try:
            async for msg in channel.history(limit=max_messages, oldest_first=False):
                scanned += 1
                newest_id = msg.id if newest_id is None or msg.id > newest_id else newest_id
                oldest_id = msg.id if oldest_id is None or msg.id < oldest_id else oldest_id

                if self.client.user and msg.author.id != self.client.user.id:
                    continue
                if not msg.embeds:
                    continue
                # Button-ID prüfen
                has_panel_button = False
                try:
                    for row in msg.components:  # type: ignore[attr-defined]
                        for comp in getattr(row, "children", []) or []:
                            if getattr(comp, "custom_id", None) == PANEL_BUTTON_CUSTOM_ID:
                                has_panel_button = True
                                break
                        if has_panel_button:
                            break
                except Exception:
                    try:
                        for comp in msg.components:
                            if getattr(comp, "custom_id", None) == PANEL_BUTTON_CUSTOM_ID:
                                has_panel_button = True
                                break
                    except Exception:
                        pass
                if not has_panel_button:
                    continue
                e = msg.embeds[0]
                footer_ok = True
                if e.footer and e.footer.text:
                    footer_ok = (e.footer.text.strip() == PANEL_FOOTER_TEXT)
                if not footer_ok:
                    continue
                title_text = (e.title or "").strip()
                description_text = (e.description or "").strip()
                prefiltered.append({
                    "message": msg,
                    "title_text": title_text,
                    "description_text": description_text,
                    "created_at": msg.created_at.isoformat() if isinstance(msg.created_at, datetime) else str(msg.created_at),
                    "author_id": msg.author.id,
                    "criteria_base": {"button": True, "footer": footer_ok},
                })
        except discord.Forbidden:
            raise PermissionError("Missing permissions to read history")
        except discord.HTTPException:
            # Teilweiser Scan; liefere was vorhanden ist
            pass

        meta = {"scanned": scanned, "oldest_id": oldest_id, "newest_id": newest_id, "completed": True}
        return prefiltered, meta


async def run(args: argparse.Namespace) -> int:
    # Load env (.env if present)
    try:
        load_dotenv()
        # Also try VPS path if running there
        load_dotenv("/root/Astra/.env", override=False)
    except Exception:
        pass

    token = os.getenv("DISCORD_TOKEN") or os.getenv("ASTRA_BOT_TOKEN")
    if not token:
        LOGGER.error("DISCORD_TOKEN / ASTRA_BOT_TOKEN not set")
        return 2

    # DB-Konfiguration: akzeptiere DB_PASS als Alias und setze DB_PORT default 3306, falls nicht gesetzt
    db_host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST")
    db_port_str = os.getenv("DB_PORT") or os.getenv("MYSQL_PORT") or "3306"
    db_user = os.getenv("DB_USER") or os.getenv("MYSQL_USER")
    db_pass = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS") or os.getenv("MYSQL_PASSWORD")
    db_name = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE")

    missing_core = []
    if not db_host:
        missing_core.append("DB_HOST")
    if not db_user:
        missing_core.append("DB_USER")
    if not db_pass:
        missing_core.append("DB_PASSWORD/DB_PASS")
    if not db_name:
        missing_core.append("DB_NAME")
    if missing_core:
        LOGGER.error("Missing required DB environment variables: %s", ", ".join(missing_core))
        LOGGER.error("Provide DB_HOST, DB_USER, DB_PASSWORD (or DB_PASS), DB_NAME. DB_PORT defaults to 3306 if omitted.")
        return 2

    try:
        db_port = int(db_port_str)  # type: ignore[arg-type]
    except ValueError:
        LOGGER.error("DB_PORT must be an integer (got %r)", db_port_str)
        return 2

    # Show target configuration (without secrets) before proceeding
    print("DB Target:")
    print(f"  host={db_host} port={db_port} user={db_user} db={db_name}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    pool = await aiomysql.create_pool(host=db_host, port=db_port, user=db_user, password=db_pass, db=db_name, autocommit=False)  # type: ignore[arg-type]
    db = DB(pool)

    # Ensure column exists
    col_exists = await db.panelmsgid_column_exists()
    if not col_exists:
        LOGGER.error("ticketsystem.panelMsgID column not found. Aborting. Run the migration first.")
        pool.close(); await pool.wait_closed()
        return 3

    intents = discord.Intents.default()
    # discord.py v2: message_content is required to read history/content
    try:
        intents.message_content = True
    except AttributeError:
        pass

    client = discord.Client(intents=intents)

    results: List[MatchResult] = []
    report_rows: List[dict] = []
    row_index = 0
    # Laufzeit-/Fortschrittsmetriken
    start_ts = time.perf_counter()
    total_scanned_channels = 0
    total_scanned_messages = 0
    slowest_channel: Optional[Tuple[int, int, float]] = None  # (guild_id, channel_id, seconds)
    # Exit-Code, der auch bei Fehlern in on_ready an den Aufrufer zurückgegeben wird
    exit_code: int = 0

    @client.event
    async def on_ready():  # type: ignore[no-redef]
        nonlocal row_index, total_scanned_channels, total_scanned_messages, slowest_channel, exit_code
        try:
            LOGGER.info("Logged in as %s", client.user)
            panels = await db.fetch_panels()
            total = len(panels)
            LOGGER.info("Loaded %d panel records from DB", total)

            scanner = PanelScanner(client)

            # Liste der geplanten Updates (msgID, description, panel_key)
            panel_updates: List[Dict[str, Any]] = []
            
            # Counter für die Zusammenfassung
            already_keys = 0
            generated_keys = 0
            unique_msg_matches = 0
            already_msg_ids = 0
            
            # 1) Panels klassifizieren & Keys generieren
            remaining_to_scan: List[Tuple[int, PanelRow, str]] = []
            row_index = 0
            
            # Wir brauchen eine Map panel_key -> panel für die Ticket-Zuordnung später
            # Nur für eindeutige Panels pro Guild!
            key_to_panel_map: Dict[str, PanelRow] = {}

            for p in panels:
                row_index += 1
                selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                selector_hash = hashlib.sha1(json.dumps(selector, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                
                # a) Key Management
                current_key = p.panel_key
                key_status = "KEY_ALREADY_SAVED"
                if not current_key:
                    current_key = str(uuid.uuid4())
                    key_status = "KEY_GENERATED"
                    generated_keys += 1
                    # Update für den Key einplanen
                    panel_updates.append({**selector, "panel_key": current_key})
                else:
                    already_keys += 1
                
                p.panel_key = current_key # Im Objekt halten für später
                key_to_panel_map[current_key] = p

                # b) Message ID / Description Management
                if p.panel_msg_id and p.panel_msg_id != 0 and p.description and p.description.strip():
                    already_msg_ids += 1
                    mr = MatchResult(p.guild_id, p.channel_id, p.thema, "ALREADY_SAVED", message_id=p.panel_msg_id, action="KEEP", panel_key=current_key, key_status=key_status)
                    results.append(mr)
                    report_rows.append({
                        "row_index": row_index, "row_selector_hash": selector_hash,
                        "status": mr.status, "action": mr.action,
                        **selector,
                        "current_message_id": p.panel_msg_id,
                        "panel_key": current_key,
                        "key_status": key_status,
                        "candidates_found": 0,
                        "reason": "panelMsgID and description already present",
                    })
                else:
                    # Merken für gruppierten Scan
                    remaining_to_scan.append((row_index, p, selector_hash))

            # 2) Gruppiert nach (guild, channel) scannen
            groups: Dict[Tuple[int, int], List[Tuple[int, PanelRow, str]]] = {}
            for (idx, p, s_hash) in remaining_to_scan:
                key = (p.guild_id, p.channel_id)
                groups.setdefault(key, []).append((idx, p, s_hash))

            scanned_channels_so_far = 0
            for (g_id, ch_id), entries in groups.items():
                scanned_channels_so_far += 1
                LOGGER.info("[Scan %d/%d] Guild=%s Channel=%s • entries=%d", scanned_channels_so_far, len(groups), g_id, ch_id, len(entries))
                guild, guild_err = await scanner._resolve_guild(g_id)
                channel_scan_error: Optional[str] = None
                prefiltered: List[Dict[str, Any]] = []
                meta: Dict[str, Any] = {}
                
                if guild is None:
                    for (idx, p, selector_hash) in entries:
                        selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "GUILD_NOT_FOUND", action="REVIEW", panel_key=p.panel_key, key_status="KEY_GENERATED" if any(u.get("panel_key") == p.panel_key for u in panel_updates) else "KEY_ALREADY_SAVED")
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "panel_key": p.panel_key,
                            "candidates_found": 0,
                            "reason": (f"Guild resolve failed: {guild_err['type']} status={guild_err.get('status')}" if guild_err else "Guild not found"),
                        })
                    continue

                try:
                    t0 = time.perf_counter()
                    prefiltered, meta = await scanner.scan_channel_messages(guild, ch_id, max_messages=args.max_messages)
                    dt = time.perf_counter() - t0
                    total_scanned_channels += 1
                    total_scanned_messages += int(meta.get("scanned") or 0)
                    if slowest_channel is None or dt > slowest_channel[2]:
                        slowest_channel = (g_id, ch_id, dt)
                    LOGGER.info("Scanned channel %s/%s in %.2fs • messages=%s", g_id, ch_id, dt, meta.get("scanned"))
                except PermissionError as e:
                    for (idx, p, selector_hash) in entries:
                        selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MISSING_PERMISSIONS", action="REVIEW", panel_key=p.panel_key)
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "panel_key": p.panel_key,
                            "reason": f"Missing permissions: {e}",
                        })
                    continue
                except Exception as e:
                    channel_scan_error = f"scan_failed: {type(e).__name__}: {e}"

                for (idx, p, selector_hash) in entries:
                    selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                    if channel_scan_error:
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "SCAN_ERROR", reason=channel_scan_error, action="REVIEW", panel_key=p.panel_key)
                        results.append(mr)
                        report_rows.append({ "row_index": idx, "status": mr.status, "action": mr.action, **selector, "panel_key": p.panel_key, "reason": channel_scan_error })
                        continue

                    cands = []
                    for item in prefiltered:
                        thema = p.thema or ""
                        if item["title_text"] == thema or item["title_text"].startswith(thema):
                            cands.append(item)

                    if not cands:
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "NO_MATCH", action="REVIEW", panel_key=p.panel_key)
                        results.append(mr)
                        report_rows.append({ "row_index": idx, "status": mr.status, "action": mr.action, **selector, "panel_key": p.panel_key, "reason": "No matching messages found" })
                    elif len(cands) > 1:
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MULTIPLE_MATCHES", action="REVIEW", panel_key=p.panel_key, candidates=len(cands))
                        results.append(mr)
                        report_rows.append({ "row_index": idx, "status": mr.status, "action": mr.action, **selector, "panel_key": p.panel_key, "candidates_found": len(cands) })
                    else:
                        item = cands[0]
                        unique_msg_matches += 1
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MATCH_FOUND", message_id=item["message"].id, action="UPDATE", panel_key=p.panel_key)
                        results.append(mr)
                        
                        # In panel_updates mergen oder neu hinzufügen
                        upd = next((u for u in panel_updates if u["guild_id"] == p.guild_id and u["channel_id"] == p.channel_id and u["thema"] == p.thema), None)
                        if upd:
                            upd["message_id"] = item["message"].id
                            upd["description"] = item["description_text"]
                        else:
                            panel_updates.append({**selector, "message_id": item["message"].id, "description": item["description_text"]})

                        report_rows.append({
                            "row_index": idx, "status": mr.status, "action": mr.action, **selector,
                            "panel_key": p.panel_key, "found_message_id": item["message"].id, "found_description": item["description_text"]
                        })

            # 3) Ticket-Zuordnung
            tickets = await db.fetch_tickets_to_map()
            LOGGER.info("Fetched %d unmapped tickets from DB", len(tickets))
            
            # Group panels by guild to check category uniqueness
            panels_by_guild: Dict[int, List[PanelRow]] = {}
            for p in panels:
                panels_by_guild.setdefault(p.guild_id, []).append(p)
            
            ticket_mappings: List[Tuple[str, int]] = [] # (key, channel_id)
            ticket_results = []
            
            mapped_tickets = 0
            ambiguous_tickets = 0
            unmapped_tickets = 0

            for t in tickets:
                g_id = t["guild_id"]
                # Wir suchen ein Panel in dieser Gilde, das für dieses Ticket verantwortlich ist.
                # Einzige Info im Ticket-Datensatz: guildID, channelID (des Tickets), opener_id, msgID (des Welcome-Embeds).
                # Wir müssen also über den Ticket-Channel gehen, um die Kategorie zu finden.
                
                guild = client.get_guild(g_id)
                if not guild:
                    ticket_results.append({**t, "status": "GUILD_NOT_FOUND"})
                    unmapped_tickets += 1
                    continue
                
                t_chan = guild.get_channel(t["channel_id"])
                if not t_chan or not hasattr(t_chan, "category_id"):
                    ticket_results.append({**t, "status": "CHANNEL_NOT_FOUND"})
                    unmapped_tickets += 1
                    continue
                
                cat_id = t_chan.category_id
                # Finde alle Panels in dieser Guild mit dieser CategoryID
                possible_panels = [p for p in panels_by_guild.get(g_id, []) if p.category_id == cat_id]
                
                if len(possible_panels) == 1:
                    target_p = possible_panels[0]
                    ticket_mappings.append((target_p.panel_key, t["channel_id"]))
                    ticket_results.append({**t, "status": "MAPPED", "panel_key": target_p.panel_key, "thema": target_p.thema})
                    mapped_tickets += 1
                elif len(possible_panels) > 1:
                    ticket_results.append({**t, "status": "AMBIGUOUS", "candidates": [p.thema for p in possible_panels]})
                    ambiguous_tickets += 1
                else:
                    ticket_results.append({**t, "status": "NO_PANEL_FOUND", "category_id": cat_id})
                    unmapped_tickets += 1

            # 4) Autoclose-State & Log Zuordnung
            ac_states = await db.fetch_autoclose_states_to_map()
            LOGGER.info("Fetched %d unmapped autoclose states from DB", len(ac_states))
            ac_mappings: List[Tuple[str, int]] = []
            
            for ac in ac_states:
                ch_id = ac["channel_id"]
                # Suche das Ticket in ticketsystem_channels (das sollte schon gemappt sein oder wir nehmen die Zuordnung von oben)
                # Da wir hier in on_ready sind, nutzen wir ticket_mappings als Cache
                p_key = next((m[0] for m in ticket_mappings if m[1] == ch_id), None)
                if not p_key:
                    # Fallback: DB fragen, falls das Ticket schon in einem früheren Run gemappt wurde
                    async with db.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("SELECT panel_key FROM ticketsystem_channels WHERE channelID=%s", (ch_id,))
                            row = await cur.fetchone()
                            if row and row[0]:
                                p_key = row[0]
                
                if p_key:
                    ac_mappings.append((p_key, ch_id))

            # Summary
            elapsed = time.perf_counter() - start_ts
            print("\n=== Scan Summary ===")
            print(f"Total panels: {total}")
            print(f"  Existing Keys      : {already_keys}")
            print(f"  New Keys generated : {generated_keys}")
            print(f"  Unique msg matches : {unique_msg_matches}")
            print(f"  Already saved IDs  : {already_msg_ids}")
            
            print(f"\nTickets (unmapped): {len(tickets)}")
            print(f"  Successfully mapped: {mapped_tickets}")
            print(f"  Ambiguous          : {ambiguous_tickets}")
            print(f"  No panel found     : {unmapped_tickets}")
            print(f"Autoclose States mapped: {len(ac_mappings)}")

            # Optional report
            if args.report:
                report_data = {
                    "meta": {
                        "total_panels": total,
                        "elapsed_seconds": elapsed,
                        "generated_keys": generated_keys,
                        "mapped_tickets": mapped_tickets,
                        "ambiguous_tickets": ambiguous_tickets,
                        "mapped_autoclose": len(ac_mappings)
                    },
                    "panels": report_rows,
                    "tickets": ticket_results
                }
                with open(args.report, "w", encoding="utf-8") as f:
                    json.dump(report_data, f, ensure_ascii=False, indent=2)
                print(f"Report written to {args.report}")

            # Apply phase
            if args.apply:
                if panel_updates:
                    p_res = await db.apply_panel_updates_batch(panel_updates)
                    print(f"Panels applied: {p_res['applied']}/{p_res['planned']} (Rollback: {p_res['rolled_back']})")
                    if p_res["errors"]: print(f"Errors: {p_res['errors']}")
                
                if ticket_mappings:
                    t_res = await db.apply_ticket_mapping(ticket_mappings)
                    print(f"Tickets mapped: {t_res['applied']}/{t_res['planned']}")
                    if t_res["errors"]: print(f"Errors: {t_res['errors']}")

                if ac_mappings:
                    ac_res = await db.apply_autoclose_mapping(ac_mappings)
                    print(f"Autoclose states mapped: {ac_res['applied']}/{ac_res['planned']}")
                    if ac_res["errors"]: print(f"Errors: {ac_res['errors']}")
            else:
                print("\nDry-run mode: no database changes were made. Use --apply to save keys and mappings.")
        except Exception:
            # Volles Traceback loggen und Fehlercode setzen
            LOGGER.exception("Unhandled exception in on_ready")
            exit_code = 1
        finally:
            # Immer sauber schließen, damit der Prozess endet
            try:
                await client.close()
            except Exception:
                pass
            # DB‑Pool nicht hier schließen – der Event‑Loop von discord.Client läuft noch.
            # Cleanup erfolgt nach client.start() im run().

    await client.start(token)

    # Zusätzlicher HTTP‑Cleanup: Manche aiohttp‑Connector‑Warnungen ("Unclosed connector")
    # können auftreten, wenn die interne Session/der Connector von discord.py noch offen ist.
    # Obwohl client.close() im on_ready‑finally bereits aufgerufen wird, stellen wir hier
    # sicher, dass die HTTP‑Session wirklich geschlossen ist.
    try:
        http = getattr(client, "http", None)
        # Mögliche Attributnamen je nach discord.py-Version
        session = None
        if http is not None:
            session = (
                getattr(http, "_HTTPClient__session", None)
                or getattr(http, "_session", None)
                or getattr(http, "session", None)
            )
        if session is not None:
            # Session schließen, falls noch offen
            if getattr(session, "closed", True) is False:
                await session.close()
            # Connector ggf. explizit schließen
            connector = getattr(session, "connector", None)
            if connector is not None and getattr(connector, "closed", True) is False:
                await connector.close()
    except Exception:
        # Dieser zusätzliche Cleanup darf den Exit‑Code nicht verdecken; Pool‑Cleanup folgt separat
        pass

    # Pool‑Cleanup NACH dem Client‑Lauf im noch aktiven Event‑Loop durchführen
    try:
        pool.close()
        await pool.wait_closed()
    except Exception as e:
        LOGGER.exception("DB pool cleanup failed: %s", e)
        # Keine Exceptions verschlucken, non‑zero Exit signalisieren
        exit_code = exit_code or 1

    return exit_code


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Restore missing ticketsystem.panelMsgID for existing panels (one-time utility)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Scan only (default), do not modify the database")
    mode.add_argument("--apply", action="store_true", help="Write panelMsgID for unique matches")
    ap.add_argument("--max-messages", type=int, default=2000, help="Max messages to scan per channel (default: 2000)")
    ap.add_argument("--batch", type=int, default=100, help="Fetch batch size per request (default: 100)")
    ap.add_argument("--report", type=str, default=None, help="Optional path to write a JSON/CSV/NDJSON report of findings")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
    args = parse_args()
    try:
        rc = asyncio.run(run(args))
    except KeyboardInterrupt:
        rc = 130
    except Exception as e:
        LOGGER.error("Fatal error: %s", e)
        rc = 1
    raise SystemExit(rc)


if __name__ == "__main__":
    main()