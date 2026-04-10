import logging
import asyncio
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, List

import discord
from discord.ext import commands
from discord import app_commands
from discord.utils import utcnow
from discord.ui import View

logging.getLogger("discord.http").setLevel(logging.ERROR)


# --- Tuning ---
BULK_CUTOFF_DAYS = 14            # Bulk delete für <= 14 Tage
SLEEP_PER_DELETE = 1.2           # stabil für alte Nachrichten
MAX_HISTORY_FETCH = 200          # msgs pro Batch bei History

# --- Jobs (persistiert in MySQL; Tabelle legst du in main.py an) ---
@dataclass
class OldDeleteJob:
    id: int
    channel_id: int
    amount: int
    requested_by: str
    status: str  # 'pending' | 'processing' | 'done'


# ---- Modal für Embeds ----
class Feedback(discord.ui.Modal, title="Erstelle dein eigenes Embed."):
    def __init__(self, *, color2: Optional[str] = None):
        super().__init__()
        self.colour = color2

    view = View()
    name = discord.ui.TextInput(
        label='Titel',
        style=discord.TextStyle.short,
        placeholder='Tippe ein, was der Titel des Embeds sein soll...',
        required=False,
    )
    description = discord.ui.TextInput(
        label='Beschreibung',
        style=discord.TextStyle.long,
        placeholder='Tippe ein, was die Beschreibung des Embeds sein soll...',
        required=True,
        max_length=4000,
    )
    footer = discord.ui.TextInput(
        label='Footer',
        style=discord.TextStyle.short,
        placeholder='Tippe ein was der Footer des Embeds sein soll...',
        required=False,
    )
    thumbnail = discord.ui.TextInput(
        label='Thumbnail',
        style=discord.TextStyle.short,
        placeholder='Füge die Url eines Thumbnails ein...',
        required=False,
    )
    image = discord.ui.TextInput(
        label='Bild',
        style=discord.TextStyle.short,
        placeholder='Füge die Url eines Bildes ein...',
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        colours = {
            "Rot": discord.Colour.red(),
            "Orange": discord.Colour.orange(),
            "Gelb": discord.Colour.yellow(),
            "Grün": discord.Colour.green(),
            "Blau": discord.Colour.blue(),
            "Blurple": discord.Colour.blurple(),
        }
        embed = discord.Embed(
            colour=colours.get(self.colour, discord.Colour.default()),
            title=self.name.value or " ",
            description=self.description.value or " ",
        )
        if self.thumbnail.value:
            embed.set_thumbnail(url=self.thumbnail.value)
        if self.image.value:
            embed.set_image(url=self.image.value)
        if self.footer.value:
            icon_url = interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None
            embed.set_footer(text=self.footer.value, icon_url=icon_url)

        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        try:
            await interaction.response.send_message('Oops! Etwas ist schiefgelaufen.', ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send('Oops! Etwas ist schiefgelaufen.', ephemeral=True)


class mod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Snipe-Store
        self.snipe_message_author: dict[int, discord.Member] = {}
        self.snipe_message_content: dict[int, str] = {}
        self.snipe_message_channel: dict[int, discord.abc.GuildChannel] = {}

        # pro Kanal: Worker + Wake-Event
        self._workers: dict[int, asyncio.Task] = {}
        self._wake_events: dict[int, asyncio.Event] = {}
        self._clear_status_messages: dict[int, int] = {}
        self._clear_bulk_deleted: dict[int, int] = {}

        # Kein cog_load -> Startup-Task
        self._startup_task = bot.loop.create_task(self._startup())

    # ---------- Startup: Recovery + Pending-Jobs anwerfen ----------
    async def _startup(self):
        await self.bot.wait_until_ready()

        # Recovery: hängengebliebene Jobs wieder aktivieren
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE clear_jobs SET status='pending' WHERE status='processing'")
                await conn.commit()

        channels = await self._get_channels_with_pending()
        for ch_id in channels:
            await self._ensure_worker(ch_id)
            self._wake_events[ch_id].set()

    async def _get_channels_with_pending(self) -> List[int]:
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT DISTINCT channel_id FROM clear_jobs WHERE status='pending'")
                rows = await cur.fetchall()
        return [int(r[0]) for r in rows]

    # ---------------- Worker-Infra ----------------
    async def _ensure_worker(self, channel_id: int):
        if channel_id not in self._wake_events:
            self._wake_events[channel_id] = asyncio.Event()
        if channel_id not in self._workers or self._workers[channel_id].done():
            self._workers[channel_id] = asyncio.create_task(self._worker_loop(channel_id))

    async def _worker_loop(self, channel_id: int):
        while True:
            job = await self._claim_next_job(channel_id)
            if not job:
                evt = self._wake_events[channel_id]
                evt.clear()
                await evt.wait()
                continue

            # Channel holen
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    # Kanal nicht erreichbar → Job entsorgen
                    await self._mark_job_done(job.id)
                    continue

            deleted_count = 0

            try:
                # Alte Nachrichten liegen hinter der Bulk-Grenze und werden gedrosselt gelöscht.
                deleted_count = await self._process_old_deletes(
                    channel,
                    job.amount,
                    job_id=job.id
                )

                status_message_id = self._clear_status_messages.pop(job.id, None)
                bulk_deleted = self._clear_bulk_deleted.pop(job.id, 0)
                if status_message_id:
                    embed = discord.Embed(
                        colour=discord.Colour.green(),
                        title="Clear abgeschlossen",
                        description=(
                            "<:Astra_accept:1141303821176422460> Der Clear-Vorgang ist abgeschlossen.\n\n"
                            f"<:Astra_punkt:1141303896745201696> **Kanal:** {channel.mention}\n"
                            f"<:Astra_punkt:1141303896745201696> **Sofort gelöscht:** "
                            f"**{bulk_deleted}** Nachricht{'' if bulk_deleted == 1 else 'en'}\n"
                            f"<:Astra_punkt:1141303896745201696> **Im Hintergrund gelöscht:** "
                            f"**{deleted_count}** alte Nachricht{'' if deleted_count == 1 else 'en'}\n\n"
                            "<:Astra_light_on:1141303864134467675> Alle geplanten Nachrichten wurden verarbeitet."
                        )
                    )
                    embed.set_author(name=job.requested_by)
                    try:
                        status_message = await channel.fetch_message(status_message_id)
                        await status_message.edit(embed=embed)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass


            except Exception as e:
                self._clear_status_messages.pop(job.id, None)
                self._clear_bulk_deleted.pop(job.id, None)
                logging.exception(e)

            finally:
                await self._mark_job_done(job.id)

    async def _claim_next_job(self, channel_id: int) -> Optional[OldDeleteJob]:
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, channel_id, amount, requested_by, status "
                    "FROM clear_jobs WHERE channel_id=%s AND status='pending' "
                    "ORDER BY id ASC LIMIT 1",
                    (channel_id,),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                job_id = int(row[0])
                await cur.execute("UPDATE clear_jobs SET status='processing' WHERE id=%s", (job_id,))
                await conn.commit()
                return OldDeleteJob(
                    id=job_id, channel_id=int(row[1]), amount=int(row[2]),
                    requested_by=str(row[3]), status='processing'
                )

    async def _mark_job_done(self, job_id: int):
        """Job aus DB löschen, wenn erledigt."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM clear_jobs WHERE id=%s", (job_id,))
                await conn.commit()

    async def _decrement_job_amount(self, job_id: int, n: int):
        """Fortschritt speichern, damit Jobs nach Restart nicht von vorn beginnen."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE clear_jobs SET amount = GREATEST(amount - %s, 0) WHERE id=%s",
                    (n, job_id)
                )
                await conn.commit()

    async def _enqueue_job(self, channel_id: int, amount: int, requested_by: str) -> int:
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO clear_jobs (channel_id, amount, requested_by, status) "
                    "VALUES (%s, %s, %s, 'pending')",
                    (channel_id, amount, requested_by)
                )
                job_id = cur.lastrowid
                await conn.commit()
                return int(job_id)

    async def _count_old_messages(self, channel: discord.TextChannel, amount: int) -> int:
        cutoff = utcnow() - timedelta(days=BULK_CUTOFF_DAYS)
        found = 0
        last_message = None

        while found < amount:
            scanned_any = False
            async for msg in channel.history(
                limit=MAX_HISTORY_FETCH,
                before=last_message or cutoff,
                oldest_first=False
            ):
                scanned_any = True
                last_message = msg

                if msg.pinned or msg.created_at >= cutoff:
                    continue

                found += 1
                if found >= amount:
                    break

            if not scanned_any:
                break

        return found

    # ---------------- Löschlogik (>14 Tage, gedrosselt) ----------------
    async def _process_old_deletes(self, channel: discord.TextChannel, amount: int, job_id: Optional[int] = None):
        cutoff = utcnow() - timedelta(days=BULK_CUTOFF_DAYS)
        remaining = amount
        last_message = None
        backoff = 0.0
        checkpoint = 0  # seit letztem DB-Update gelöschte Anzahl

        while remaining > 0:
            scanned_any = False
            async for msg in channel.history(
                limit=MAX_HISTORY_FETCH,
                before=last_message or cutoff,
                oldest_first=False
            ):
                scanned_any = True
                last_message = msg
                if msg.pinned:
                    continue

                if msg.created_at >= cutoff:
                    continue

                try:
                    await msg.delete()  # kein reason bei PartialMessage
                    remaining -= 1
                    checkpoint += 1
                    backoff = 0.0

                    # alle 10 Deletes Fortschritt persistieren
                    if job_id and checkpoint >= 10:
                        await self._decrement_job_amount(job_id, checkpoint)
                        checkpoint = 0

                    await asyncio.sleep(SLEEP_PER_DELETE + random.uniform(0.0, 0.2))
                    if remaining == 0:
                        break
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    continue
                except discord.HTTPException as e:
                    if getattr(e, "status", None) == 429:
                        backoff = min(5.0, backoff + 0.7)
                        await asyncio.sleep(1.8 + backoff)
                    else:
                        await asyncio.sleep(0.9)
                    continue
            if not scanned_any:
                # nichts mehr zu löschen → Job sauber beenden
                remaining = 0
                break

        # Restlichen Fortschritt verbuchen
        if job_id and checkpoint > 0:
            await self._decrement_job_amount(job_id, checkpoint)

        return amount - remaining

    # ---------------- Commands ----------------

    @app_commands.command(name="kick", description="Kicke einen Nutzer vom Server.")
    @app_commands.describe(user="Das Mitglied, das gekickt werden soll.")
    @app_commands.describe(reason="Grund für den Kick.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        """Kicke einen User."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT channelID FROM modlog WHERE serverID = (%s)", (interaction.guild.id,))
                result = await cursor.fetchone()

        if result:
            channel = interaction.guild.get_channel(int(result[0]))
            embed = discord.Embed(colour=discord.Colour.orange(), description=f"Der User {user} (`{user.id}`) wurde gekickt.")
            embed.add_field(name="👤 Member:", value=user.mention, inline=False)
            embed.add_field(name="👮 Moderator:", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
            embed.add_field(name="📄 Grund:", value=reason, inline=False)
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)
            if channel:
                await channel.send(embed=embed)

        if user.guild_permissions.kick_members:
            embed = discord.Embed(colour=discord.Colour.red(), description=f"Der User {user.mention} kann nicht gekickt werden, da er die Rechte `Mitglieder Kicken` hat.")
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        confirm = discord.Embed(colour=discord.Colour.orange(), description=f"Der User {user} (`{user.id}`) wurde gekickt.")
        confirm.add_field(name="🎛️ Server:", value=interaction.guild.name, inline=False)
        confirm.add_field(name="👮 Moderator:", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
        confirm.add_field(name="📄 Grund:", value=reason, inline=False)
        confirm.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

        dm = discord.Embed(colour=discord.Colour.orange(), description=f"Hey {user.mention}! \nDu wurdest vom Server **{interaction.guild.name}** gekickt! Mehr Informationen hier:")
        dm.add_field(name="🎛️ Server:", value=interaction.guild.name, inline=False)
        dm.add_field(name="👮 Moderator:", value=interaction.user.mention, inline=False)
        dm.add_field(name="📄 Grund:", value=reason, inline=False)
        dm.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

        try:
            await user.send(embed=dm)
        except Exception as e:
            logging.exception(e)

        await user.kick(reason=reason)
        await interaction.response.send_message(embed=confirm, ephemeral=False)

    @app_commands.command(name="ban", description="Banne einen Nutzer vom Server.")
    @app_commands.describe(user="Das Mitglied, das gebannt werden soll.")
    @app_commands.describe(reason="Grund für den Bann.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        """Banne einen User."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT channelID FROM modlog WHERE serverID = (%s)", (interaction.guild.id,))
                result = await cursor.fetchone()

        if result:
            channel = interaction.guild.get_channel(int(result[0]))
            embed = discord.Embed(colour=discord.Colour.orange(), description=f"Der User {user} (`{user.id}`) wurde gebannt.")
            embed.add_field(name="👤 Member:", value=user.mention, inline=False)
            embed.add_field(name="👮 Moderator:", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
            embed.add_field(name="📄 Grund:", value=reason, inline=False)
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            if channel:
                await channel.send(embed=embed)

        if user.guild_permissions.kick_members:
            embed = discord.Embed(colour=discord.Colour.red(), description=f"Der User {user.mention} kann nicht gebannt werden, da er die Rechte `Mitglieder Bannen` hat.")
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        confirm = discord.Embed(colour=discord.Colour.orange(), description=f"Der User {user} (`{user.id}`) wurde gebannt.")
        confirm.add_field(name="🎛️ Server:", value=interaction.guild.name, inline=False)
        confirm.add_field(name="👮 Moderator:", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
        confirm.add_field(name="📄 Grund:", value=reason, inline=False)
        confirm.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

        dm = discord.Embed(colour=discord.Colour.orange(), description=f"Hey {user.mention}! \nDu wurdest vom Server **{interaction.guild.name}** gebannt! Mehr Informationen hier:")
        dm.add_field(name="🎛️ Server:", value=interaction.guild.name, inline=False)
        dm.add_field(name="👮 Moderator:", value=interaction.user.mention, inline=False)
        dm.add_field(name="📄 Grund:", value=reason, inline=False)
        dm.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        try:
            await user.send(embed=dm)
        except Exception as e:
            logging.exception(e)

        await user.ban(reason=reason)
        await interaction.response.send_message(embed=confirm, ephemeral=False)

    @app_commands.command(name="clear", description="Löscht Nachrichten: schnell (≤14 Tage) & alte im Hintergrund.")
    @app_commands.describe(channel="Der Kanal, in dem gelöscht werden soll.")
    @app_commands.describe(amount="Wie viele Nachrichten sollen gelöscht werden? (max. 300)")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_messages=True, read_message_history=True)
    async def clear(self, interaction: discord.Interaction, channel: discord.TextChannel, amount: int):
        """Automatisch: Bulk für ≤14 Tage, ältere als persistente Jobs im Hintergrund."""
        if amount <= 0:
            embed = discord.Embed(
                colour=discord.Colour.red(),
                description="<:Astra_x:1141303954555289600> Die Anzahl muss größer als **0** sein."
            )
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if amount > 300:
            embed = discord.Embed(
                colour=discord.Colour.red(),
                description="<:Astra_x:1141303954555289600> Deine Zahl darf nicht größer als **300** sein."
            )
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer()

        cutoff = utcnow() - timedelta(days=BULK_CUTOFF_DAYS)
        total_deleted = 0
        status_embed = discord.Embed(
            colour=discord.Colour.blue(),
            title="Nachrichten werden gelöscht",
            description=(
                "<:Astra_time:1141303932061233202> Der Clear-Vorgang läuft.\n\n"
                f"<:Astra_punkt:1141303896745201696> **Kanal:** {channel.mention}\n"
                f"<:Astra_punkt:1141303896745201696> **Angefragt:** **{amount}** Nachrichten\n\n"
                "<:Astra_light_on:1141303864134467675> Nachrichten werden geprüft und gelöscht."
            )
        )
        status_embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        status_message = await interaction.followup.send(embed=status_embed, wait=True)

        try:
            # 1) Bulk (≤14 Tage)
            deleted_bulk = await channel.purge(
                limit=amount + 1,
                after=cutoff,
                bulk=True,
                reason=f"/clear von {interaction.user} ({amount})",
                check=lambda m: not m.pinned and m.id != status_message.id
            )

            total_deleted += len(deleted_bulk)
            remaining = amount - total_deleted

            scheduled = 0
            if remaining > 0:
                # 2) Nur tatsächlich vorhandene alte Nachrichten als Job persistieren.
                scheduled = await self._count_old_messages(channel, remaining)
                if scheduled > 0:
                    job_id = await self._enqueue_job(channel.id, scheduled, str(interaction.user))
                    self._clear_status_messages[job_id] = status_message.id
                    self._clear_bulk_deleted[job_id] = total_deleted
                    await self._ensure_worker(channel.id)
                    self._wake_events[channel.id].set()

            if scheduled > 0:
                title = "Clear läuft im Hintergrund weiter"
                colour = discord.Colour.blue()
                lines = [
                    "<:Astra_time:1141303932061233202> Der schnelle Teil ist fertig. Alte Nachrichten werden weiter im Hintergrund gelöscht.\n",
                    (
                        f"<:Astra_punkt:1141303896745201696> **Sofort gelöscht:** "
                        f"**{total_deleted}** Nachricht{'' if total_deleted == 1 else 'en'}"
                    ),
                    (
                        f"<:Astra_punkt:1141303896745201696> **Im Hintergrund:** "
                        f"**{scheduled}** alte Nachricht{'' if scheduled == 1 else 'en'}"
                    ),
                ]
            else:
                title = "Clear abgeschlossen"
                colour = discord.Colour.green()
                lines = [
                    "<:Astra_accept:1141303821176422460> Der Clear-Vorgang ist abgeschlossen.\n",
                    (
                        f"<:Astra_punkt:1141303896745201696> **Gelöscht:** "
                        f"**{total_deleted}** Nachricht{'' if total_deleted == 1 else 'en'}"
                    ),
                ]
                if remaining > 0:
                    lines.append(
                        "<:Astra_info:1141303860556738620> **Keine weiteren alten Nachrichten gefunden.**"
                    )
            embed = discord.Embed(
                colour=colour,
                title=title,
                description="\n".join(lines)
            )
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            await status_message.edit(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                colour=discord.Colour.red(),
                title="Clear fehlgeschlagen",
                description=(
                    "<:Astra_x:1141303954555289600> Beim Löschen ist ein Fehler aufgetreten.\n\n"
                    f"<:Astra_punkt:1141303896745201696> `{e}`"
                )
            )
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            await status_message.edit(embed=embed)

    @app_commands.command(name="embedfy", description="Erstelle ein schönes Embed.")
    @app_commands.describe(color="Optional: Farbnamen wie Rot, Orange, Gelb, Grün, Blau oder Blurple.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embedfy(self, interaction: discord.Interaction, color: Optional[str] = None):
        await interaction.response.send_modal(Feedback(color2=color))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild:
            self.snipe_message_author[message.guild.id] = message.author
            self.snipe_message_content[message.guild.id] = message.content or ""
            self.snipe_message_channel[message.guild.id] = message.channel

    @app_commands.command(name="unban", description="Entbanne einen Nutzer per Tag (Name#1234).")
    @app_commands.describe(usertag="Tag des Nutzers im Format Name#1234.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, usertag: str):
        """Entbanne einen User (Name#1234)."""
        try:
            member_name, member_discriminator = usertag.split('#', 1)
        except ValueError:
            return await interaction.response.send_message("Format: `Name#1234`", ephemeral=True)

        banned_users = [entry async for entry in interaction.guild.bans(limit=2000)]
        for ban_entry in banned_users:
            user = ban_entry.user
            if (user.name, user.discriminator) == (member_name, member_discriminator):
                await interaction.guild.unban(user)
                return await interaction.response.send_message(
                    f"<:Astra_accept:1141303821176422460> **Der User {usertag} wurde entbannt.**"
                )

        await interaction.response.send_message("User nicht in der Bannliste gefunden.", ephemeral=True)
        return None

    @app_commands.command(name="banlist", description="Zeigt eine Liste aller gebannten Nutzer.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(ban_members=True)
    async def banlist(self, interaction: discord.Interaction):
        """Zeigt eine Liste mit gebannten Usern."""
        users = [entry async for entry in interaction.guild.bans(limit=2000)]
        if not users:
            return await interaction.response.send_message(
                '<:Astra_x:1141303954555289600> **Hier gibt es keine gebannten User.**',
                ephemeral=True
            )

        lines = ['__**Username**__ — __**Grund**__']
        for entry in users:
            name = f"🤖 {entry.user}" if entry.user.bot else str(entry.user)
            reason = entry.reason or "—"
            lines.append(f"{name} — {reason}")

        text = "\n".join(lines)
        for chunk_start in range(0, len(text), 1800):
            chunk = text[chunk_start:chunk_start + 1800]
            embed = discord.Embed(title="Bann Liste", description=chunk, color=discord.Color.red())
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            embed.set_footer(text=f"{len(users)} gebannte User auf dem Server.")
            if chunk_start == 0:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(mod(bot))
