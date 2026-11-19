"""
Lightweight local IPC server for Bot actions (publish/update/move ticket panels).

Constraints:
- Binds only to 127.0.0.1
- Requires shared secret via header 'X-Astra-IPC-Key'
- Runs inside the Discord bot event loop (aiohttp.web)

This module intentionally has no imports from the API process.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional
import discord

from aiohttp import web

logger = logging.getLogger("astra.ipc")


class BotIPC:
    def __init__(self, bot, *, host: str = "127.0.0.1", port: int = 8765, secret: Optional[str] = None):
        self.bot = bot
        self.host = host
        self.port = port
        self.secret = secret or os.environ.get("ASTRA_IPC_KEY") or ""
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    def _auth(self, request: web.Request) -> bool:
        return self.secret and request.headers.get("X-Astra-IPC-Key") == self.secret

    async def _json(self, request: web.Request) -> dict:
        try:
            return await request.json()
        except Exception:
            return {}

    async def _handle_publish(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            from cogs.ticket import api_publish_ticket_panel  # local import to avoid hard coupling
            guild_id = int(data.get("guild_id"))
            channel_id = int(data.get("channel_id"))
            category_id = int(data.get("category_id")) if data.get("category_id") is not None else 0
            role_id = int(data.get("role_id")) if data.get("role_id") is not None else 0
            title = (data.get("title") or "").strip()
            description = (data.get("description") or "").strip()
            if not guild_id or not channel_id or not title:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            res = await api_publish_ticket_panel(
                self.bot,
                guild_id=guild_id,
                channel_id=channel_id,
                category_id=category_id,
                role_id=role_id,
                title=title,
                description=description,
            )
            return web.json_response({"success": True, "status": "published", **{k: str(v) for k, v in res.items()}}, status=200)
        except asyncio.TimeoutError:
            return web.json_response({"success": False, "code": "timeout"}, status=504)
        except PermissionError:
            return web.json_response({"success": False, "code": "permission_denied"}, status=403)
        except Exception:
            logger.exception("IPC publish failed")
            return web.json_response({"success": False, "code": "publish_failed"}, status=500)

    async def _handle_update(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            from cogs.ticket import api_update_ticket_panel
            guild_id = int(data.get("guild_id"))
            channel_id = int(data.get("channel_id"))
            message_id = int(data.get("message_id"))
            title = (data.get("title") or None)
            description = (data.get("description") or None)
            if not guild_id or not channel_id or not message_id:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            await api_update_ticket_panel(
                self.bot,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                title=title,
                description=description,
            )
            return web.json_response({"success": True, "status": "updated"}, status=200)
        except asyncio.TimeoutError:
            return web.json_response({"success": False, "code": "timeout"}, status=504)
        except FileNotFoundError:
            return web.json_response({"success": False, "code": "message_not_found"}, status=410)
        except Exception:
            logger.exception("IPC update failed")
            return web.json_response({"success": False, "code": "update_failed"}, status=500)

    async def _handle_move(self, request: web.Request) -> web.Response:
        """
        Sicheres Verschieben eines Panels:
        1) Neue Nachricht im Zielkanal posten
        2) Neue Message-ID/Config speichern
        3) Alte Nachricht löschen
        Bei Fehlern: Alter Zustand bleibt erhalten.
        """
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            from cogs.ticket import api_publish_ticket_panel
            guild_id = int(data.get("guild_id"))
            old_channel_id = int(data.get("old_channel_id"))
            old_message_id = int(data.get("old_message_id"))
            new_channel_id = int(data.get("new_channel_id"))
            category_id = int(data.get("category_id")) if data.get("category_id") is not None else 0
            role_id = int(data.get("role_id")) if data.get("role_id") is not None else 0
            title = (data.get("title") or "").strip()
            description = (data.get("description") or "").strip()
            if not all([guild_id, old_channel_id, old_message_id, new_channel_id]) or not title:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)

            # 1) Neue Nachricht posten
            res = await api_publish_ticket_panel(
                self.bot,
                guild_id=guild_id,
                channel_id=new_channel_id,
                category_id=category_id,
                role_id=role_id,
                title=title,
                description=description,
            )
            new_message_id = int(res.get("message_id"))

            # 2) Alte Nachricht sicher löschen (wenn vorhanden)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                raise RuntimeError("Guild not available")
            old_ch = guild.get_channel(old_channel_id) or await guild.fetch_channel(old_channel_id)
            try:
                if hasattr(old_ch, "get_partial_message"):
                    await old_ch.get_partial_message(old_message_id).delete()
                else:
                    msg = await old_ch.fetch_message(old_message_id)
                    await msg.delete()
            except Exception:
                # Nicht kritisch: Teilfehler melden
                return web.json_response({
                    "success": True,
                    "status": "moved_old_delete_failed",
                    "channel_id": str(new_channel_id),
                    "message_id": str(new_message_id),
                }, status=200)

            return web.json_response({
                "success": True,
                "status": "moved",
                "channel_id": str(new_channel_id),
                "message_id": str(new_message_id),
            }, status=200)
        except PermissionError:
            return web.json_response({"success": False, "code": "permission_denied"}, status=403)
        except asyncio.TimeoutError:
            return web.json_response({"success": False, "code": "timeout"}, status=504)
        except Exception:
            logger.exception("IPC move failed")
            return web.json_response({"success": False, "code": "move_failed"}, status=500)

    async def _handle_delete(self, request: web.Request) -> web.Response:
        """
        Löscht eine veröffentlichte Panel-Nachricht in Discord.
        Anforderungen:
        - 404 (Not Found) ist zulässig und wird als success zurückgegeben ("message_missing").
        - Bei fehlenden Berechtigungen 403 zurückgeben, damit der Aufrufer die DB nicht löscht.
        - Keine DB-Änderungen hier – nur Discord-Operationen.
        """
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            guild_id = int(data.get("guild_id"))
            channel_id = int(data.get("channel_id"))
            message_id = int(data.get("message_id"))
            if not guild_id or not channel_id or not message_id:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)

            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return web.json_response({"success": False, "code": "guild_unavailable"}, status=503)

            ch = guild.get_channel(channel_id)
            if ch is None:
                try:
                    ch = await guild.fetch_channel(channel_id)
                except discord.NotFound:  # type: ignore
                    # Kanal selbst existiert nicht mehr -> Nachricht ist zwangsläufig weg
                    return web.json_response({"success": True, "status": "message_missing"}, status=200)
                except discord.Forbidden:  # type: ignore
                    return web.json_response({"success": False, "code": "permission_denied"}, status=403)
                except Exception:
                    logger.exception("IPC delete: fetch_channel failed")
                    return web.json_response({"success": False, "code": "delete_failed"}, status=500)

            # Berechtigungen prüfen
            try:
                me = guild.me or await guild.fetch_member(self.bot.user.id)  # type: ignore
            except Exception:
                logger.exception("IPC delete: fetch_member(self) failed")
                me = None
            perms = ch.permissions_for(me) if (me is not None and hasattr(ch, "permissions_for")) else None
            if not perms or not getattr(perms, "manage_messages", False):
                # Fallback: Manche Bots können auch ohne manage_messages eigene Nachrichten löschen,
                # aber wenn Permissions klar fehlen, geben wir 403 zurück.
                # Löschversuch erfolgt dennoch – wenn erfolgreich, prima; wenn nicht, 403.
                try:
                    # Teilschnittstelle verwenden, wenn verfügbar
                    if hasattr(ch, "get_partial_message"):
                        await ch.get_partial_message(message_id).delete()
                    else:
                        msg = await ch.fetch_message(message_id)
                        await msg.delete()
                except discord.Forbidden:  # type: ignore
                    return web.json_response({"success": False, "code": "permission_denied"}, status=403)
                except discord.NotFound:  # type: ignore
                    return web.json_response({"success": True, "status": "message_missing"}, status=200)
                except Exception:
                    logger.exception("IPC delete failed (no perms branch)")
                    return web.json_response({"success": False, "code": "delete_failed"}, status=500)
                return web.json_response({"success": True, "status": "deleted"}, status=200)

            # Regulärer Löschpfad
            try:
                if hasattr(ch, "get_partial_message"):
                    await ch.get_partial_message(message_id).delete()
                else:
                    msg = await ch.fetch_message(message_id)
                    await msg.delete()
                return web.json_response({"success": True, "status": "deleted"}, status=200)
            except discord.NotFound:  # type: ignore
                return web.json_response({"success": True, "status": "message_missing"}, status=200)
            except discord.Forbidden:  # type: ignore
                return web.json_response({"success": False, "code": "permission_denied"}, status=403)
            except Exception:
                logger.exception("IPC delete failed")
                return web.json_response({"success": False, "code": "delete_failed"}, status=500)
        except asyncio.TimeoutError:
            return web.json_response({"success": False, "code": "timeout"}, status=504)
        except Exception:
            logger.exception("IPC delete handler error")
            return web.json_response({"success": False, "code": "delete_failed"}, status=500)

    async def _handle_delete_complete(self, request: web.Request) -> web.Response:
        """
        Zentraler IPC-Handler für die vollständige Löschung eines Panels via panel_key.
        Ruft die zentrale Bot-Funktion 'delete_panel_completely' auf.
        """
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            from cogs.ticket import delete_panel_completely
            guild_id = int(data.get("guild_id"))
            panel_key = data.get("panel_key")
            if not guild_id or not panel_key:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            
            res = await delete_panel_completely(self.bot, guild_id, panel_key)
            return web.json_response({"success": True, **res}, status=200)
        except RuntimeError as e:
            return web.json_response({"success": False, "code": str(e)}, status=404 if "not found" in str(e).lower() else 500)
        except Exception:
            logger.exception("IPC complete delete failed")
            return web.json_response({"success": False, "code": "delete_failed"}, status=500)

    async def start(self):
        app = web.Application()
        app.add_routes([
            web.post("/ipc/panel/publish", self._handle_publish),
            web.post("/ipc/panel/update", self._handle_update),
            web.post("/ipc/panel/move", self._handle_move),
            web.post("/ipc/panel/delete", self._handle_delete),
            web.post("/ipc/panel/delete_complete", self._handle_delete_complete),
            # Ressourcen-Endpunkte für Dashboard-Dropdowns
            web.post("/ipc/resources/roles", self._handle_roles),
            web.post("/ipc/resources/channels", self._handle_channels),
            web.post("/ipc/resources/categories", self._handle_categories),
        ])
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self.host, port=self.port)
        await self._site.start()
        logger.info("Bot IPC started on %s:%s", self.host, self.port)

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    # =============================
    #    Ressourcen: Rollen/Chans
    # =============================

    async def _handle_roles(self, request: web.Request) -> web.Response:
        """Liefert Rollen einer Guild (ohne @everyone)."""
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            guild_id_raw = data.get("guild_id")
            if guild_id_raw is None:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            guild_id = int(guild_id_raw)
            g = self.bot.get_guild(guild_id)
            if g is None:
                return web.json_response({"success": False, "code": "guild_not_found"}, status=404)

            out = []
            for r in g.roles:
                # @everyone nicht anzeigen
                if r.name == "@everyone":
                    continue
                color_val = 0
                try:
                    color_val = int(getattr(r.color, "value", 0))
                except Exception:
                    color_val = 0
                out.append({
                    "id": str(r.id),
                    "name": r.name,
                    "color": color_val,
                })
            return web.json_response({"success": True, "roles": out}, status=200)
        except Exception:
            logger.exception("IPC roles handler error")
            return web.json_response({"success": False, "code": "roles_failed"}, status=500)

    async def _handle_channels(self, request: web.Request) -> web.Response:
        """Liefert Kanäle einer Guild (alle Typen außer Kategorien; parent_id und Typ enthalten)."""
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            guild_id_raw = data.get("guild_id")
            if guild_id_raw is None:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            guild_id = int(guild_id_raw)
            g = self.bot.get_guild(guild_id)
            if g is None:
                return web.json_response({"success": False, "code": "guild_not_found"}, status=404)

            out = []
            # g.channels enthält bereits alle Chans; Kategorien separieren wir, daher skip bei CategoryChannel
            for ch in g.channels:
                try:
                    # Kategorien hier auslassen, diese liefert eigener Endpoint
                    if isinstance(ch, discord.CategoryChannel):
                        continue
                except Exception:
                    # Falls Typprüfung fehlschlägt, weiter – UI kann "type" auswerten
                    pass
                parent_id = getattr(ch, "category_id", None)
                ch_type = getattr(ch, "type", None)
                ch_type_val = int(getattr(ch_type, "value", 0)) if ch_type is not None else 0
                out.append({
                    "id": str(getattr(ch, "id", 0)),
                    "name": getattr(ch, "name", str(getattr(ch, "id", "unknown"))),
                    "type": ch_type_val,
                    "parent_id": str(parent_id) if parent_id else None,
                })
            return web.json_response({"success": True, "channels": out}, status=200)
        except Exception:
            logger.exception("IPC channels handler error")
            return web.json_response({"success": False, "code": "channels_failed"}, status=500)

    async def _handle_categories(self, request: web.Request) -> web.Response:
        """Liefert nur Kategorien (CategoryChannel) einer Guild."""
        if not self._auth(request):
            return web.json_response({"success": False, "code": "unauthorized"}, status=401)
        data = await self._json(request)
        try:
            guild_id_raw = data.get("guild_id")
            if guild_id_raw is None:
                return web.json_response({"success": False, "code": "invalid_payload"}, status=400)
            guild_id = int(guild_id_raw)
            g = self.bot.get_guild(guild_id)
            if g is None:
                return web.json_response({"success": False, "code": "guild_not_found"}, status=404)

            out = []
            for cat in getattr(g, "categories", []) or []:
                out.append({
                    "id": str(getattr(cat, "id", 0)),
                    "name": getattr(cat, "name", str(getattr(cat, "id", "unknown"))),
                })
            return web.json_response({"success": True, "categories": out}, status=200)
        except Exception:
            logger.exception("IPC categories handler error")
            return web.json_response({"success": False, "code": "categories_failed"}, status=500)
