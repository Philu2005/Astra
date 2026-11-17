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
from typing import Optional, List, Tuple

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

    async def update_panel_msg_id(self, guild_id: int, channel_id: int, message_id: int) -> None:
        q = (
            "UPDATE ticketsystem "
            "SET panelMsgID=%s "
            "WHERE guildID=%s AND channelID=%s AND (panelMsgID IS NULL OR panelMsgID=0)"
        )
        async with self.pool.acquire() as conn:
            try:
                async with conn.cursor() as cur:
                    await cur.execute(q, (int(message_id), int(guild_id), int(channel_id)))
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

    async def find_candidate_messages(self, guild_id: int, channel_id: int, thema: str, *,
                                      max_messages: int = 2000, batch_size: int = 100) -> List[discord.Message]:
        guild = self.client.get_guild(int(guild_id))
        if guild is None:
            # Signal to caller via custom exceptions is overkill; return [] and let caller classify if needed
            return []
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            try:
                channel = await guild.fetch_channel(int(channel_id))  # type: ignore[assignment]
            except discord.Forbidden:
                raise PermissionError("Missing permissions to fetch channel")
            except discord.NotFound:
                # Invalid channel ID
                return []
            except discord.HTTPException:
                return []
        if not isinstance(channel, discord.TextChannel):
            # Not a text channel → not eligible for panels in our implementation
            return []

        me = guild.me or await guild.fetch_member(self.client.user.id)  # type: ignore
        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.read_message_history:
            raise PermissionError("Missing permissions to read history")

        candidates: List[discord.Message] = []
        fetched = 0
        last_id: Optional[int] = None
        consecutive_errors = 0

        while fetched < max_messages:
            try:
                try:
                    # discord.py <2.0 compatibility
                    history = await channel.history(
                        limit=batch_size,
                        before=discord.Object(id=last_id) if last_id else None,
                        oldest_first=False,
                    ).flatten()  # type: ignore[attr-defined]
                except AttributeError:
                    # discord.py 2.0+: async iterator
                    history_iter = channel.history(
                        limit=batch_size,
                        before=discord.Object(id=last_id) if last_id else None,
                        oldest_first=False,
                    )
                    history = [m async for m in history_iter]
                consecutive_errors = 0
            except discord.Forbidden:
                # Lost permission mid-scan
                raise PermissionError("Missing permissions to read history")
            except discord.HTTPException as e:
                # Backoff with cap; stop after limited retries to avoid endless loops
                consecutive_errors += 1
                if consecutive_errors > 5:
                    break
                sleep_for = min(3.0 * consecutive_errors, 15.0)
                await asyncio.sleep(sleep_for)
                continue

            if not history:
                break

            for msg in history:
                fetched += 1
                # Advance pagination window: use the oldest message id from this page when done
                last_id = msg.id if last_id is None or msg.id < last_id else last_id
                # Author must be the bot itself
                if self.client.user and msg.author.id != self.client.user.id:
                    continue
                # Panel messages must contain an embed and a button with our custom_id
                if not msg.embeds:
                    continue
                # Check components for our known button custom_id
                has_panel_button = False
                try:
                    for row in msg.components:  # type: ignore[attr-defined]
                        # row could be ActionRow
                        for comp in getattr(row, "children", []) or []:
                            if getattr(comp, "custom_id", None) == PANEL_BUTTON_CUSTOM_ID:
                                has_panel_button = True
                                break
                        if has_panel_button:
                            break
                except Exception:
                    # Components introspection not supported – try alternative attribute
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
                # Check footer text if present
                footer_ok = True
                if e.footer and e.footer.text:
                    footer_ok = (e.footer.text.strip() == PANEL_FOOTER_TEXT)

                # Title must match the stored thema (panel title at creation). To support older
                # panels, allow prefix matches as fallback.
                title_ok = True
                if thema:
                    title_text = (e.title or "").strip()
                    title_ok = (title_text == thema) or (title_text.startswith(thema))

                if footer_ok and title_ok:
                    candidates.append(msg)

                if fetched >= max_messages:
                    break

            if fetched >= max_messages:
                break

        return candidates


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

    @client.event
    async def on_ready():  # type: ignore[no-redef]
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

        for p in panels:
            if p.panel_msg_id and p.panel_msg_id != 0:
                results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "ALREADY_SAVED", message_id=p.panel_msg_id))
                already += 1
                continue
            try:
                try:
                    cands = await scanner.find_candidate_messages(p.guild_id, p.channel_id, p.thema, max_messages=args.max_messages, batch_size=args.batch)
                except PermissionError:
                    results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "MISSING_PERMISSIONS"))
                    denied += 1
                    continue
                except Exception as e:
                    results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "ERROR", reason=str(e)))
                    errors += 1
                    continue

                if not cands:
                    # Distinguish some common cases
                    guild = client.get_guild(int(p.guild_id))
                    if guild is None:
                        results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "GUILD_NOT_FOUND"))
                    else:
                        ch = guild.get_channel(int(p.channel_id))
                        if ch is None:
                            results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "INVALID_CHANNEL"))
                        else:
                            results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "NO_MATCH"))
                    not_found += 1
                    continue
                if len(cands) > 1:
                    results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "MULTIPLE_MATCHES", reason=f"{len(cands)} candidates"))
                    multiple += 1
                    continue

                msg = cands[0]
                results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "MATCH_FOUND", message_id=msg.id))
                unique_matches.append((p, msg.id))

            except Exception as e:
                results.append(MatchResult(p.guild_id, p.channel_id, p.thema, "ERROR", reason=str(e)))
                errors += 1

        # Summary
        print("\n=== Scan Summary ===")
        print(f"Total panels: {total}")
        print(f"  ALREADY_SAVED      : {already}")
        print(f"  MATCH_FOUND        : {len(unique_matches)}")
        print(f"  MULTIPLE_MATCHES   : {multiple}")
        print(f"  NO_MATCH           : {not_found}")
        print(f"  MISSING_PERMISSIONS: {denied}")
        print(f"  ERROR              : {errors}")

        # Optional report
        if args.report:
            try:
                if args.report.lower().endswith(".json"):
                    with open(args.report, "w", encoding="utf-8") as f:
                        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
                elif args.report.lower().endswith(".csv"):
                    with open(args.report, "w", newline="", encoding="utf-8") as f:
                        w = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()) if results else ["guild_id","channel_id","thema","status","message_id","reason"])  # type: ignore
                        w.writeheader()
                        for r in results:
                            w.writerow(asdict(r))
                else:
                    with open(args.report, "w", encoding="utf-8") as f:
                        for r in results:
                            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
                print(f"Report written to {args.report}")
            except Exception as e:
                LOGGER.warning("Could not write report: %s", e)

        # Apply phase
        if args.apply and unique_matches:
            updated = 0
            for p, mid in unique_matches:
                try:
                    await db.update_panel_msg_id(p.guild_id, p.channel_id, mid)
                    updated += 1
                except Exception as e:
                    LOGGER.error("Failed to update panelMsgID for guild=%s channel=%s: %s", p.guild_id, p.channel_id, e)
            print(f"Applied updates: {updated}")
        elif not args.apply:
            print("Dry-run mode: no database changes were made. Use --apply to write panelMsgID for unique matches.")

        # Clean shutdown
        await client.close()
        pool.close(); await pool.wait_closed()

    await client.start(token)
    return 0


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
