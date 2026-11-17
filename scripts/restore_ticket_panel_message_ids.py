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
from dataclasses import dataclass, asdict
import hashlib
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
    role_id: Optional[int]
    category_id: Optional[int]
    panel_msg_id: Optional[int]


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
        # Fetch all panels for which we may need to restore panelMsgID (including those already set to classify as ALREADY_SAVED)
        # Detect column presence first to avoid catching unrelated SQL exceptions.
        q_with = (
            "SELECT guildID, channelID, thema, roleID, categoryID, panelMsgID FROM ticketsystem"
        )
        q_without = (
            "SELECT guildID, channelID, thema, roleID, categoryID FROM ticketsystem"
        )
        items: List[PanelRow] = []
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Decide query by checking column existence
                await cur.execute(
                    "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ticketsystem' AND COLUMN_NAME = 'panelMsgID'"
                )
                has_col = bool(await cur.fetchone())
                if has_col:
                    await cur.execute(q_with)
                    rows = await cur.fetchall()
                    for g, ch, thema, rid, cid, mid in rows:
                        items.append(
                            PanelRow(
                                guild_id=int(g),
                                channel_id=int(ch),
                                thema=str(thema or ""),
                                role_id=int(rid) if rid else None,
                                category_id=int(cid) if cid else None,
                                panel_msg_id=int(mid) if mid else None,
                            )
                        )
                else:
                    await cur.execute(q_without)
                    rows = await cur.fetchall()
                    for g, ch, thema, rid, cid in rows:
                        items.append(
                            PanelRow(
                                guild_id=int(g),
                                channel_id=int(ch),
                                thema=str(thema or ""),
                                role_id=int(rid) if rid else None,
                                category_id=int(cid) if cid else None,
                                panel_msg_id=None,
                            )
                        )
        return items

    async def update_panel_msg_id(self, guild_id: int, channel_id: int, message_id: int,
                                  *, role_id: Optional[int], category_id: Optional[int], thema: str) -> None:
        q = (
            "UPDATE ticketsystem "
            "SET panelMsgID=%s "
            "WHERE guildID=%s AND channelID=%s AND "
            "(panelMsgID IS NULL OR panelMsgID=0) AND "
            "((roleID IS NULL AND %s IS NULL) OR roleID=%s) AND "
            "((categoryID IS NULL AND %s IS NULL) OR categoryID=%s) AND "
            "(thema <=> %s)"
        )
        async with self.pool.acquire() as conn:
            try:
                async with conn.cursor() as cur:
                    await cur.execute(q, (
                        int(message_id), int(guild_id), int(channel_id),
                        role_id, role_id, category_id, category_id, thema
                    ))
                    affected = cur.rowcount
                    if affected == 1:
                        await conn.commit()
                    else:
                        # Either already set or row not found; never overwrite
                        await conn.rollback()
                        raise RuntimeError(
                            f"Unsafe update (affected={affected}) for guild={guild_id} channel={channel_id}; aborted"
                        )
            except Exception:
                # Safety net: rollback any partial changes
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise


class PanelScanner:
    def __init__(self, client: discord.Client):
        self.client = client

    async def _resolve_guild(self, guild_id: int) -> Optional[discord.Guild]:
        guild = self.client.get_guild(int(guild_id))
        if guild is not None:
            return guild
        # Versuch eines Live-Fetch (sparsam, nur einmal pro Gruppe sinnvoll)
        try:
            guild = await self.client.fetch_guild(int(guild_id))  # type: ignore[attr-defined]
            return guild  # type: ignore[return-value]
        except Exception:
            return None

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
                prefiltered.append({
                    "message": msg,
                    "title_text": title_text,
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

    token = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN")
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
    intents.messages = True  # required to read guild text channel history
    intents.message_content = False  # not needed

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

            unique_matches: List[Tuple[PanelRow, int]] = []
            already = 0
            multiple = 0
            not_found = 0
            denied = 0
            errors = 0

            # 1) Bereits gesetzte IDs zuerst klassifizieren (KEEP) – kein Discord-Scan nötig
            remaining: List[PanelRow] = []
            for p in panels:
                row_index += 1
                selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                selector_hash = hashlib.sha1(json.dumps(selector, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                if p.panel_msg_id and p.panel_msg_id != 0:
                    mr = MatchResult(p.guild_id, p.channel_id, p.thema, "ALREADY_SAVED", message_id=p.panel_msg_id, action="KEEP")
                    results.append(mr)
                    report_rows.append({
                        "row_index": row_index, "row_selector_hash": selector_hash,
                        "status": mr.status, "action": mr.action,
                        **selector,
                        "current_message_id": p.panel_msg_id,
                        "candidates_found": 0,
                        "reason": "panelMsgID already present",
                    })
                    already += 1
                else:
                    # Merken für gruppierten Scan
                    remaining.append(p)

            # 2) Gruppiert nach (guild, channel) nur einmal scannen und Ergebnisse für alle Panels des Kanals nutzen
            groups: Dict[Tuple[int, int], List[Tuple[int, PanelRow, str]]] = {}
            # Wir brauchen weiterhin row_index je Panel; daher speichern wir ihn mit ab
            row_index = 0
            for p in remaining:
                row_index += 1
                key = (p.guild_id, p.channel_id)
                selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                selector_hash = hashlib.sha1(json.dumps(selector, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                groups.setdefault(key, []).append((row_index, p, selector_hash))

            scanned_channels_so_far = 0
            for (g_id, ch_id), entries in groups.items():
                scanned_channels_so_far += 1
                LOGGER.info("[Scan %d/%d] Guild=%s Channel=%s • entries=%d", scanned_channels_so_far, len(groups), g_id, ch_id, len(entries))
                # Gilde auflösen (Cache oder Fetch)
                try:
                    guild = await scanner._resolve_guild(g_id)
                except discord.HTTPException:
                    LOGGER.exception("Guild resolve failed for guild=%s channel=%s", g_id, ch_id)
                    guild = None
                channel_scan_error: Optional[str] = None
                prefiltered: List[Dict[str, Any]] = []
                meta: Dict[str, Any] = {}
                if guild is None:
                    # Alle zugehörigen Panels als GUILD_NOT_FOUND klassifizieren
                    for (idx, p, selector_hash) in entries:
                        selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "GUILD_NOT_FOUND", action="REVIEW")
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "candidates_found": 0,
                            "reason": "Guild not found (cache+fetch failed)",
                            "guild_cache_miss": True,
                        })
                    not_found += len(entries)
                    continue
                # Channel einmal scannen
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
                    LOGGER.exception("Permission error scanning channel guild=%s channel=%s", g_id, ch_id)
                    for (idx, p, selector_hash) in entries:
                        selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MISSING_PERMISSIONS", action="REVIEW")
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "candidates_found": None,
                            "reason": f"Missing permissions to read history: {e}",
                        })
                    denied += len(entries)
                    continue
                except (discord.HTTPException, OSError, asyncio.TimeoutError) as e:
                    LOGGER.exception("Channel scan failed for guild=%s channel=%s", g_id, ch_id)
                    channel_scan_error = f"scan_failed: {type(e).__name__}: {e}"

                # Für jeden Panel‑Eintrag im Kanal: Kandidaten anhand Thema ableiten
                for (idx, p, selector_hash) in entries:
                    selector = {"guild_id": p.guild_id, "channel_id": p.channel_id, "role_id": p.role_id, "category_id": p.category_id, "thema": p.thema}
                    try:
                        if channel_scan_error:
                            mr = MatchResult(p.guild_id, p.channel_id, p.thema, "SCAN_ERROR", reason=channel_scan_error, action="REVIEW")
                            results.append(mr)
                            report_rows.append({
                                "row_index": idx, "row_selector_hash": selector_hash,
                                "status": mr.status, "action": mr.action,
                                **selector,
                                "current_message_id": p.panel_msg_id,
                                "candidates_found": None,
                                "reason": channel_scan_error,
                                "scan_meta": meta,
                            })
                            errors += 1
                            continue

                        # Filter für dieses Panel‑Thema
                        cands: List[Tuple[discord.Message, Dict[str, Any]]] = []
                        for item in prefiltered:
                            title_text = item.get("title_text") or ""
                            thema = p.thema or ""
                            if thema:
                                if title_text == thema or title_text.startswith(thema):
                                    # Kriterien für diesen Eintrag erweitern
                                    crit = dict(item.get("criteria_base") or {})
                                    crit.update({
                                        "title_exact": (title_text == thema),
                                        "title_prefix": (title_text.startswith(thema) and title_text != thema),
                                    })
                                    cands.append((item["message"], crit))

                        if not cands:
                            # Kanal existiert?
                            if meta.get("channel_fetch") == "not_found":
                                mr = MatchResult(p.guild_id, p.channel_id, p.thema, "INVALID_CHANNEL", action="REVIEW")
                                results.append(mr)
                                report_rows.append({
                                    "row_index": idx, "row_selector_hash": selector_hash,
                                    "status": "CHANNEL_NOT_FOUND", "action": mr.action,
                                    **selector,
                                    "current_message_id": p.panel_msg_id,
                                    "candidates_found": 0,
                                    "reason": "Channel not found in guild",
                                    "scan_meta": meta,
                                })
                            else:
                                mr = MatchResult(p.guild_id, p.channel_id, p.thema, "NO_MATCH", action="REVIEW")
                                results.append(mr)
                                report_rows.append({
                                    "row_index": idx, "row_selector_hash": selector_hash,
                                    "status": mr.status, "action": mr.action,
                                    **selector,
                                    "current_message_id": p.panel_msg_id,
                                    "candidates_found": 0,
                                    "reason": "No matching messages found",
                                    "scan_meta": meta,
                                })
                            not_found += 1
                            continue

                        if len(cands) > 1:
                            mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MULTIPLE_MATCHES", reason=f"{len(cands)} candidates", action="REVIEW", candidates=len(cands))
                            results.append(mr)
                            report_rows.append({
                                "row_index": idx, "row_selector_hash": selector_hash,
                                "status": mr.status, "action": mr.action,
                                **selector,
                                "current_message_id": p.panel_msg_id,
                                "candidates_found": len(cands),
                                "reason": mr.reason,
                                "candidates": [
                                    {
                                        "message_id": m.id,
                                        "created_at": m.created_at.isoformat(),
                                        "author_id": m.author.id,
                                        "author_is_bot": (client.user and m.author.id == client.user.id),
                                        "criteria": crit,
                                    } for (m, crit) in cands
                                ],
                                "scan_meta": meta,
                            })
                            multiple += 1
                            continue

                        (msg, crit) = cands[0]
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "MATCH_FOUND", message_id=msg.id, action="UPDATE", candidates=1)
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "found_message_id": msg.id,
                            "found_created_at": msg.created_at.isoformat(),
                            "author_id": msg.author.id,
                            "author_is_bot": (client.user and msg.author.id == client.user.id),
                            "criteria": crit,
                            "candidates_found": 1,
                            "reason": "unique match",
                        })
                        unique_matches.append((p, msg.id))

                    except (discord.HTTPException, OSError, asyncio.TimeoutError) as e:
                        LOGGER.exception("Entry handling failed for guild=%s channel=%s row=%s", p.guild_id, p.channel_id, idx)
                        mr = MatchResult(p.guild_id, p.channel_id, p.thema, "SCAN_ERROR", reason=str(e), action="REVIEW")
                        results.append(mr)
                        report_rows.append({
                            "row_index": idx, "row_selector_hash": selector_hash,
                            "status": mr.status, "action": mr.action,
                            **selector,
                            "current_message_id": p.panel_msg_id,
                            "candidates_found": None,
                            "reason": f"SCAN_ERROR: {type(e).__name__}: {e}",
                        })
                        errors += 1

            # Summary
            elapsed = time.perf_counter() - start_ts
            print("\n=== Scan Summary ===")
            print(f"Total panels: {total}")
            print(f"  ALREADY_SAVED      : {already}")
            print(f"  MATCH_FOUND        : {len(unique_matches)}")
            print(f"  MULTIPLE_MATCHES   : {multiple}")
            print(f"  NO_MATCH           : {not_found}")
            print(f"  MISSING_PERMISSIONS: {denied}")
            print(f"  SCAN_ERROR         : {errors}")
            print(f"Channels scanned     : {total_scanned_channels}")
            print(f"Messages scanned     : {total_scanned_messages}")
            if slowest_channel:
                print(f"Slowest channel      : guild={slowest_channel[0]} channel={slowest_channel[1]} in {slowest_channel[2]:.2f}s")
            print(f"Elapsed              : {elapsed:.2f}s")

            # Optional report
            if args.report:
                try:
                    if args.report.lower().endswith(".json"):
                        with open(args.report, "w", encoding="utf-8") as f:
                            json.dump({
                                "meta": {
                                    "total_panels": total,
                                    "already_saved": already,
                                    "match_found": len(unique_matches),
                                    "multiple_matches": multiple,
                                    "no_match": not_found,
                                    "missing_permissions": denied,
                                    "scan_error": errors,
                                    "channels_scanned": total_scanned_channels,
                                    "messages_scanned": total_scanned_messages,
                                    "slowest_channel": {
                                        "guild_id": slowest_channel[0] if slowest_channel else None,
                                        "channel_id": slowest_channel[1] if slowest_channel else None,
                                        "seconds": slowest_channel[2] if slowest_channel else None,
                                    },
                                    "elapsed_seconds": elapsed,
                                },
                                "rows": report_rows,
                            }, f, ensure_ascii=False, indent=2)
                    elif args.report.lower().endswith(".csv"):
                        with open(args.report, "w", newline="", encoding="utf-8") as f:
                            fieldnames = sorted({k for row in report_rows for k in row.keys()}) if report_rows else [
                                "guild_id","channel_id","thema","status","action","found_message_id","current_message_id"
                            ]
                            w = csv.DictWriter(f, fieldnames=fieldnames)
                            w.writeheader()
                            for r in report_rows:
                                w.writerow(r)
                    else:
                        with open(args.report, "w", encoding="utf-8") as f:
                            f.write(json.dumps({"meta": {"elapsed_seconds": elapsed}, "rows": []}, ensure_ascii=False) + "\n")
                    print(f"Report written to {args.report}")
                except (OSError, IOError, json.JSONDecodeError) as e:
                    LOGGER.exception("Could not write report: %s", e)
                    exit_code = 1
                    return

            # Apply phase
            if args.apply and unique_matches:
                updated = 0
                for p, mid in unique_matches:
                    try:
                        await db.update_panel_msg_id(p.guild_id, p.channel_id, mid, role_id=p.role_id, category_id=p.category_id, thema=p.thema or "")
                        updated += 1
                    except Exception as e:
                        LOGGER.error("Failed to update panelMsgID for guild=%s channel=%s: %s", p.guild_id, p.channel_id, e)
                print(f"Applied updates: {updated}")
            elif not args.apply:
                print("Dry-run mode: no database changes were made. Use --apply to write panelMsgID for unique matches.")
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
            try:
                pool.close(); await pool.wait_closed()
            except Exception:
                pass

    await client.start(token)
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
