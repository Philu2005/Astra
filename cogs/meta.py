import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from discord.app_commands import Group
import aiohttp
from discord.ui.button import Button
from discord.ui.view import View
import requests
import asyncio
from collections import deque
from datetime import timezone
import logging
from utils.logger import setup_logging
setup_logging()

def convert(time):
    pos = ["s", "m", "h", "d"]
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24}
    unit = time[-1]
    if unit not in pos:
        return -1
    try:
        val = int(time[:-1])
    except:
        return -2
    return val * time_dict[unit]


# @app_commands.context_menu(name="User Info")
# async def userinfo_context(interaction: discord.Interaction, member: discord.Member):
#
#     banneruser = await interaction.client.fetch_user(member.id)
#
#     guild = interaction.guild
#     member = guild.get_member(member.id)
#
#     if member is None:
#         try:
#             member = await guild.fetch_member(member.id)
#         except:
#             member = interaction.user
#
#     created = discord.utils.format_dt(member.created_at, "R")
#     joined = discord.utils.format_dt(member.joined_at, "R")
#
#     top_role = member.top_role if not member.top_role.is_default() else None
#
#     # ================= BADGES =================
#     badges = []
#     flags = member.public_flags
#
#     BADGE_MAP = {
#         "staff": "<:discordemployee:1494713034793553931>",
#         "partner": "<:partner:1494713075960647710>",
#         "hypesquad": "<:hypesquad:1494712603673493565>",
#         "hypesquad_balance": "<:balance:1494713178183962724>",
#         "hypesquad_bravery": "<:bravery:1494712600817307659>",
#         "hypesquad_brilliance": "<:brillance:1494712602360680560>",
#         "bug_hunter": "<:bughunterlv1:1494713049783996619>",
#         "bug_hunter_level_2": "<:bughunterlv2:1494713060076556542>",
#         "early_supporter": "<:earlysupporter:1494712935463780502>",
#         "verified_bot_developer": "<:earlyverifiedbotdeveloper:1494714480704360548>",
#         "active_developer": "<:quest:1494714496571281448>",
#         "discord_certified_moderator": "<:certifiedmoderator:1494714457274847424>",
#     }
#
#     for attr, emoji in BADGE_MAP.items():
#         if getattr(flags, attr, False):
#             badges.append(emoji)
#
#     if hasattr(flags, "moderator_performance_curriculum") and flags.moderator_performance_curriculum:
#         badges.append("<:moderatorprogram:1494714464161894551>")
#
#     # ================= BOOST =================
#     if member.premium_since:
#         now = discord.utils.utcnow()
#         diff = now - member.premium_since
#         days = diff.days
#
#         badges.append("<:nitro1:1494713979401011271>")
#
#         if days >= 730:
#             badges.append("<:boost9:1494714456226402416>")
#         elif days >= 540:
#             badges.append("<:boost8:1494714462375248213>")
#         elif days >= 365:
#             badges.append("<:boost7:1494714475188584668>")
#         elif days >= 270:
#             badges.append("<:boost6:1494714476509794314>")
#         elif days >= 180:
#             badges.append("<:boost5:1494714485095534763>")
#         elif days >= 90:
#             badges.append("<:boost4:1494714494624989195>")
#         elif days >= 60:
#             badges.append("<:boost3:1494714467550892102>")
#         elif days >= 30:
#             badges.append("<:boost2:1494714493413101639>")
#         else:
#             badges.append("<:boost1:1494714465684291745>")
#
#     if member.id == 1141303828625489940:
#         badges.append("<:LastMeadows:1494713907749716008>")
#
#     badge_text = ", ".join(badges) if badges else "—"
#
#     # ================= STATUS =================
#     status_map = {
#         discord.Status.online: "Online",
#         discord.Status.idle: "Idle",
#         discord.Status.dnd: "DND",
#         discord.Status.offline: "Offline"
#     }
#
#     user_status = status_map.get(member.status, "Offline")
#
#     activities_list = []
#
#     if member.activities:
#         for act in member.activities:
#             if isinstance(act, discord.CustomActivity):
#                 content = ""
#                 if act.emoji:
#                     content += f"{act.emoji} "
#                 if act.name:
#                     content += act.name
#                 if content:
#                     activities_list.append(content)
#
#             elif isinstance(act, discord.Spotify):
#                 activities_list.append(f"**Spotify:** {act.title} - {act.artist}")
#
#             elif isinstance(act, discord.Game):
#                 start_time = ""
#                 if act.start:
#                     start_time = f" (seit {discord.utils.format_dt(act.start, 'R')})"
#                 activities_list.append(f"**Spielt:** {act.name}{start_time}")
#
#             elif isinstance(act, discord.Streaming):
#                 activities_list.append(f"**Streamt:** {act.name}")
#
#             elif isinstance(act, discord.Activity):
#                 prefix = ""
#                 if act.type == discord.ActivityType.watching:
#                     prefix = "**Schaut**: "
#                 elif act.type == discord.ActivityType.listening:
#                     prefix = "**Hört**: "
#                 elif act.type == discord.ActivityType.competing:
#                     prefix = "**Tritt an in**: "
#
#                 start_time = ""
#                 if act.start:
#                     start_time = f" (seit {discord.utils.format_dt(act.start, 'R')})"
#
#                 if not prefix:
#                     activities_list.append(f"**{act.name}**{start_time}")
#                 else:
#                     activities_list.append(f"{prefix}{act.name}{start_time}")
#
#     if activities_list:
#         activity = "\n".join(activities_list)
#     else:
#         activity = f"Keine Aktivität ({user_status})"
#
#     # ================= EMBED =================
#     embed = discord.Embed(color=discord.Color.blue())
#
#     embed.set_author(
#         name=str(member),
#         icon_url=member.display_avatar.url
#     )
#
#     embed.description = f"Account erstellt {created}\nBeigetreten {joined}"
#
#     embed.set_thumbnail(url=member.display_avatar.url)
#
#     if banneruser.banner:
#         embed.set_image(url=banneruser.banner.url)
#
#     embed.add_field(
#         name="Info",
#         value=(
#             f"ID: `{member.id}`\n"
#             f"Bot: {'Ja' if member.bot else 'Nein'}\n"
#             f"Rolle: {top_role.mention if top_role else '@everyone'}"
#         ),
#         inline=False
#     )
#
#     embed.add_field(name="Badges", value=badge_text, inline=False)
#     embed.add_field(name="Status", value=activity, inline=False)
#     embed.add_field(name="Avatar", value=f"[Link]({member.display_avatar.url})", inline=False)
#
#     await interaction.response.send_message(embed=embed)



@app_commands.guild_only()
class InfoGroup(app_commands.Group):
    def __init__(self, bot):
        self.bot = bot  # <--- Hinzufügen!
        super().__init__(name="info", description="Informationen über den Server")

    @app_commands.command(name="kanal", description="Zeigt Informationen über einen Text- oder Sprachkanal an.")
    @app_commands.describe(textchannel="Optional: Wähle einen Textkanal, über den Infos angezeigt werden sollen.")
    @app_commands.describe(voicechannels="Optional: Wähle einen Sprachkanal, über den Infos angezeigt werden sollen.")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def channelinfo(self, interaction: discord.Interaction, textchannel: discord.TextChannel = None, voicechannels: discord.VoiceChannel = None):
        """Zeigt einige Infos über einen Channel."""
        if textchannel is None:
            channels = interaction.channel
        if isinstance(textchannel, discord.TextChannel):
            channel = textchannel
            embed = discord.Embed(colour=discord.Color.green())
            embed.add_field(name=f"🆔 ID", value=f"{channel.id}", inline=False)
            embed.add_field(name="⚙️ Erstellt", value=f"{discord.utils.format_dt(channel.created_at, 'R')}", inline=False)
            embed.add_field(name="🗂 Kategorie", value=f"{channel.category.name if channel.category.name else 'Keine Kategorie.'}", inline=False)
            embed.add_field(name="🖌 Beschreibung", value=f"{channel.topic if channel.topic else 'Keine Beschreibung.'}", inline=False)
            embed.add_field(name="🔢 Position", value=f"{channel.position}", inline=False)
            embed.set_author(name=f"Kanal Info {channel.name}", icon_url=interaction.user.avatar)
            await interaction.response.send_message(embed=embed)
            return
        if isinstance(voicechannels, discord.VoiceChannel):
            channel = voicechannels
            embed = discord.Embed(colour=discord.Color.green())
            embed.add_field(name=f"🆔 ID", value=f"{channel.id}", inline=False)
            embed.add_field(name="⏱️ Erstellt", value=f"{discord.utils.format_dt(channel.created_at, 'R')}", inline=False)
            embed.add_field(name="🗂 Kategorie", value=f"{channel.category.name if channel.category.name else 'Keine Kategorie.'}", inline=False)
            if channel.user_limit == 0:
                embed.add_field(name=f"📊 Limit", value=f"Kein Limit", inline=False)
            else:
                embed.add_field(name=f"📊 Limit", value=f"{channel.user_limit}", inline=False)
            embed.add_field(name=f"🔊 Bitrate", value=f"{channel.bitrate / 1000} kbps", inline=False)
            embed.set_author(name=f"Kanal Info {channel.name}", icon_url=interaction.user.avatar)
            await interaction.response.send_message(embed=embed)
            return

    # @app_commands.command(name="user", description="Zeigt Informationen über einen Nutzer.")
    # @app_commands.describe(member="Optional: Das Mitglied, über das Infos angezeigt werden sollen.")
    # @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    # async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
    #
    #     # ✅ FIX 1: richtig setzen
    #     if member is None:
    #         member = interaction.user
    #
    #     banneruser = await interaction.client.fetch_user(member.id)
    #
    #     # Wir holen das Member-Objekt direkt von der aktuellen Guild
    #     # interaction.user ist oft nur ein Member-Objekt mit eingeschränkten Daten
    #     # Daher suchen wir ihn spezifisch in der Guild.
    #     guild = interaction.guild
    #     member = guild.get_member(member.id)
    #
    #     # Falls er nicht im Cache ist (was bei aktiven Intents unwahrscheinlich ist, aber vorkommen kann)
    #     if member is None:
    #         try:
    #             member = await guild.fetch_member(banneruser.id)
    #         except:
    #             member = interaction.user
    #
    #     created = discord.utils.format_dt(member.created_at, "R")
    #     joined = discord.utils.format_dt(member.joined_at, "R")
    #
    #     top_role = member.top_role if not member.top_role.is_default() else None
    #
    #     # ================= BADGES =================
    #     badges = []
    #     flags = member.public_flags
    #
    #     BADGE_MAP = {
    #         "staff": "<:discordemployee:1494713034793553931>",
    #         "partner": "<:partner:1494713075960647710>",
    #         "hypesquad": "<:hypesquad:1494712603673493565>",
    #         "hypesquad_balance": "<:balance:1494713178183962724>",
    #         "hypesquad_bravery": "<:bravery:1494712600817307659>",
    #         "hypesquad_brilliance": "<:brillance:1494712602360680560>",
    #         "bug_hunter": "<:bughunterlv1:1494713049783996619>",
    #         "bug_hunter_level_2": "<:bughunterlv2:1494713060076556542>",
    #         "early_supporter": "<:earlysupporter:1494712935463780502>",
    #         "verified_bot_developer": "<:earlyverifiedbotdeveloper:1494714480704360548>",
    #         "active_developer": "<:quest:1494714496571281448>",
    #         "discord_certified_moderator": "<:certifiedmoderator:1494714457274847424>",
    #     }
    #
    #     for attr, emoji in BADGE_MAP.items():
    #         if getattr(flags, attr, False):
    #             badges.append(emoji)
    #
    #     if hasattr(flags, "moderator_performance_curriculum") and flags.moderator_performance_curriculum:
    #         badges.append("<:moderatorprogram:1494714464161894551>")
    #
    #     # ================= BOOST =================
    #     if member.premium_since:
    #         now = discord.utils.utcnow()
    #         diff = now - member.premium_since
    #         days = diff.days
    #
    #         badges.append("<:nitro1:1494713979401011271>")
    #
    #         if days >= 730:
    #             badges.append("<:boost9:1494714456226402416>")
    #         elif days >= 540:
    #             badges.append("<:boost8:1494714462375248213>")
    #         elif days >= 365:
    #             badges.append("<:boost7:1494714475188584668>")
    #         elif days >= 270:
    #             badges.append("<:boost6:1494714476509794314>")
    #         elif days >= 180:
    #             badges.append("<:boost5:1494714485095534763>")
    #         elif days >= 90:
    #             badges.append("<:boost4:1494714494624989195>")
    #         elif days >= 60:
    #             badges.append("<:boost3:1494714467550892102>")
    #         elif days >= 30:
    #             badges.append("<:boost2:1494714493413101639>")
    #         else:
    #             badges.append("<:boost1:1494714465684291745>")
    #
    #     if member.id == 1141303828625489940:
    #         badges.append("<:LastMeadows:1494713907749716008>")
    #
    #     badge_text = ", ".join(badges) if badges else "—"
    #
    #     # ================= STATUS FIX =================
    #     status_map = {
    #         discord.Status.online: "Online",
    #         discord.Status.idle: "Idle",
    #         discord.Status.dnd: "DND",
    #         discord.Status.offline: "Offline"
    #     }
    #
    #     # Status aus member.status ermitteln
    #     user_status = status_map.get(member.status, "Offline")
    #
    #     # Aktivitäten sammeln
    #     activities_list = []
    #
    #     if member.activities:
    #         for act in member.activities:
    #             if isinstance(act, discord.CustomActivity):
    #                 # Custom Status (der Text unter dem Namen)
    #                 content = ""
    #                 if act.emoji:
    #                     content += f"{act.emoji} "
    #                 if act.name:
    #                     content += act.name
    #                 if content:
    #                     activities_list.append(content)
    #
    #             elif isinstance(act, discord.Spotify):
    #                 # Spotify (Liedtitel)
    #                 activities_list.append(f"**Spotify**: {act.title} - {act.artist}")
    #
    #             elif isinstance(act, discord.Game):
    #                 # Einfaches Spiel
    #                 start_time = ""
    #                 if act.start:
    #                     start_time = f" (seit {discord.utils.format_dt(act.start, 'R')})"
    #                 activities_list.append(f"**Spielt**: {act.name}{start_time}")
    #
    #             elif isinstance(act, discord.Streaming):
    #                 # Stream
    #                 activities_list.append(f"**Streamt**: [{act.name}]({act.url})")
    #
    #             elif isinstance(act, discord.Activity):
    #                 # Rich Presence (z.B. PyCharm, VS Code, Discord RPC)
    #                 prefix = ""
    #                 if act.type == discord.ActivityType.watching:
    #                     prefix = "**Schaut**: "
    #                 elif act.type == discord.ActivityType.listening:
    #                     prefix = "**Hört**: "
    #                 elif act.type == discord.ActivityType.competing:
    #                     prefix = "**Tritt an in**: "
    #
    #                 start_time = ""
    #                 if act.start:
    #                     start_time = f" (seit {discord.utils.format_dt(act.start, 'R')})"
    #
    #                 # Wenn es kein spezieller Typ ist, einfach nur den Namen fett anzeigen
    #                 if not prefix:
    #                     activities_list.append(f"**{act.name}**{start_time}")
    #                 else:
    #                     activities_list.append(f"{prefix}{act.name}{start_time}")
    #
    #     # Finale Anzeige
    #     if activities_list:
    #         activity = "\n" + "\n".join(activities_list)
    #     else:
    #         activity = f"Keine Aktivität ({user_status})"
    #
    #     # ================= EMBED =================
    #     embed = discord.Embed(color=discord.Color.blue())
    #
    #     embed.set_author(
    #         name=str(member),
    #         icon_url=member.display_avatar.url
    #     )
    #
    #     embed.description = f"Account erstellt {created}\nBeigetreten {joined}"
    #
    #     embed.set_thumbnail(url=member.display_avatar.url)
    #
    #     if banneruser.banner:
    #         embed.set_image(url=banneruser.banner.url)
    #
    #     embed.add_field(
    #         name="Info",
    #         value=(
    #             f"ID: `{member.id}`\n"
    #             f"Bot: {'Ja' if member.bot else 'Nein'}\n"
    #             f"Rolle: {top_role.mention if top_role else '@everyone'}"
    #         ),
    #         inline=False
    #     )
    #
    #     embed.add_field(name="Badges", value=badge_text, inline=False)
    #     embed.add_field(name="Status", value=activity, inline=False)
    #     embed.add_field(name="Avatar", value=f"[Link]({member.display_avatar.url})", inline=False)
    #
    #     await interaction.response.send_message(embed=embed)

    @app_commands.command(name="server", description="Zeigt Informationen über den Server.")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def serverinfo(self, interaction: discord.Interaction):
        """Zeigt einige Infos über einen Server."""
        roles = len(interaction.guild.roles)
        embed = discord.Embed(color=0x3498db)  # Golden
        embed.set_thumbnail(url=interaction.guild.icon)
        embed.add_field(name='Name', value=f"{interaction.guild.name}", inline=True)
        embed.add_field(name='ID', value=f"{interaction.guild.id}", inline=True)
        embed.add_field(name='Inhaber', value=f"{interaction.guild.owner}", inline=False)
        embed.add_field(name='<:Astra_user2:1141303942324699206> Members', value=f"{interaction.guild.member_count}", inline=False)
        embed.add_field(name='<:Astra_calender:1141303828625489940> Erstellt', value=f"{discord.utils.format_dt(interaction.guild.created_at, 'R')}", inline=False)
        embed.add_field(name="<:Astra_boost:1141303827107164270> Boosts", value=f"{interaction.guild.premium_subscription_count}")
        embed.add_field(name="<:Astra_boost:1141303827107164270> Boost level", value=f"{interaction.guild.premium_tier}", inline=True)
        embed.add_field(name='<:Astra_time:1141303932061233202> AFK Voice Timeout', value=f'{int(interaction.guild.afk_timeout / 60)} min', inline=True)
        if interaction.guild.system_channel:
            embed.add_field(name='<:Astra_settings2:1141303910557040660> Standard Kanal', value=f'#{interaction.guild.system_channel}', inline=False)
        embed.add_field(name='<:Astra_file1:1141303837181886494> Rollen', value=f"{roles}", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="icon", description="Zeigt das Server-Icon.")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def servericon(self, interaction: discord.Interaction):
        """Zeigt das Server Profilbild."""
        guild = interaction.guild
        embed = discord.Embed(colour=discord.Colour.green(), description=f"Servericon von {guild.name}")
        embed.set_author(name=f"Servericon von {guild.name}", icon_url=interaction.guild.icon)
        embed.set_image(url=guild.icon)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rolle", description="Zeigt Informationen über eine Rolle.")
    @app_commands.describe(role="Wähle die Rolle, über die Informationen angezeigt werden sollen.")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        """Get information about a role."""
        em = discord.Embed(description=f'Info über {role.name}', color=discord.Color.green())
        em.title = role.name
        thing = str(discord.utils.format_dt(role.created_at, 'R'))
        em.add_field(name="🆔 Role ID", value=f"{str(role.id)}", inline=True)
        em.add_field(name="⏱ Erstellt", value=f"Created at {thing}", inline=False)
        em.add_field(name='🖌 Farbe', value=f"{str(role.colour)}", inline=False)
        em.add_field(name='👥 Personen in der Rolle', value=f"{str(len(role.members))} von {interaction.guild.member_count} Mitgliedern.", inline=True)
        await interaction.response.send_message(embed=em)

    @app_commands.command(name="wetter", description="Zeigt Wetterinformationen zu einer Stadt.")
    @app_commands.describe(stadt="Name der Stadt (z. B. Berlin, Wien, Zürich).")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def weather(self, interaction: discord.Interaction, stadt: str):
        """Zeigt dir einige Infos über das Wetter einer Stadt."""
        try:
            async with aiohttp.ClientSession() as cs:
                async with cs.get(f"https://api.openweathermap.org/data/2.5/weather?appid=bf254c2299576dc022583728cfaf7971&q=" + stadt.replace(" ", "+")) as r:
                    data = await r.json()
                    icon = data['weather'][0]['icon']
                    embed = discord.Embed(colour=discord.Colour.green(), title=f"Weather", description=f"Mal sehen...")
                    embed.add_field(name=f"🗽 Standort", value=f"{data['name']}")
                    embed.add_field(name=f"☁️ Wetter", value=f"{data['weather'][0]['main']} - {data['weather'][0]['description']}", inline=False)
                    embed.add_field(name=f"🔥 Temperatur", value=f"{int((float(data['main']['temp']))) - 273}°C")
                    embed.add_field(name=f"👆 Fühlt sich an wie", value=f"{int((float(data['main']['feels_like']))) - 273}°C")
                    embed.add_field(name=f"💧 Luftfeuchtigkeit", value=f"{int((float(data['main']['humidity'])))}%", inline=False)
                    embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
                    embed.set_thumbnail(url=f"https://openweathermap.org/img/wn/{icon}@2x.png")
                    await interaction.response.send_message(embed=embed)
        except:
            embed = discord.Embed(colour=discord.Colour.red(), description=f"Stadt `{stadt}` nicht gefunden.")
            embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
            await interaction.response.send_message(embed=embed)
            return


class meta(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="umfrage", description="Erstelle eine Umfrage mit bis zu 7 Optionen.")
    @app_commands.describe(titel="Titel der Umfrage.")
    @app_commands.describe(optionen="Kommagetrennte Liste der Optionen (z. B. Rot, Blau, Grün).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def poll(self, interaction: discord.Interaction, titel: str, optionen: str):
        """Erstelle eine Umfrage."""
        optionen_liste = [opt.strip() for opt in optionen.split(',')]
        reactions = ['🔵', '🟢', '🟡', '🔴', '🟠', '🟣', '🟤']
        emojis = reactions[:len(optionen_liste)]

        embed = discord.Embed(title=titel, description="Wählen Sie eine Option", color=discord.Color.blue())
        embed.add_field(
            name="Optionen",
            value='\n'.join([f"{emoji} - {option}" for emoji, option in zip(emojis, optionen_liste)]),
            inline=False
        )

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()

        for emoji in emojis:
            await message.add_reaction(emoji)

        event_queue = deque()

        def check(reaction, user):
            return (
                reaction.message.id == message.id and
                str(reaction.emoji) in emojis and
                not user.bot
            )

        async def reaction_listener():
            while True:
                done, _ = await asyncio.wait([
                    asyncio.create_task(self.bot.wait_for('reaction_add', check=check)),
                    asyncio.create_task(self.bot.wait_for('reaction_remove', check=check))
                ], return_when=asyncio.FIRST_COMPLETED)

                event_queue.append(1)  # Irgendein Event wurde erkannt

        async def updater():
            while True:
                if event_queue:
                    event_queue.clear()  # Alle "alten" Events verwerfen, nur neuester Stand zählt

                    msg = await interaction.channel.fetch_message(message.id)
                    stimmen = {emoji: 0 for emoji in emojis}

                    for reaction in msg.reactions:
                        if str(reaction.emoji) in stimmen:
                            async for user in reaction.users():
                                if not user.bot:
                                    stimmen[str(reaction.emoji)] += 1

                    total_votes = sum(stimmen.values())
                    results = []
                    for emoji in emojis:
                        votes = stimmen[emoji]
                        percentage = (votes / total_votes * 100) if total_votes > 0 else 0
                        bar = '█' * int(percentage // 10) + '░' * (10 - int(percentage // 10))
                        results.append(f"{emoji} - {votes} Stimmen | {percentage:.1f}% [{bar}]")

                    new_embed = discord.Embed(
                        title=f"Abstimmung Ergebnisse: {titel}",
                        description="Aktuelle Ergebnisse",
                        color=discord.Color.green()
                    )
                    new_embed.add_field(name="Optionen", value="\n".join(results), inline=False)
                    await msg.edit(embed=new_embed)

                await asyncio.sleep(2)  # Alle 2 Sekunden prüfen

        # Beides gleichzeitig starten
        await asyncio.gather(reaction_listener(), updater())

    @app_commands.command(name="invites", description="Zeigt die Einladungen eines Nutzers.")
    @app_commands.describe(user="Optional: Mitglied, dessen Einladungen angezeigt werden sollen. Standard: du selbst.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def invites(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zeigt die Einladungen eines Users."""
        if user is None:
            user = interaction.user
        if user is not None:
            totalInvites = 0
            for i in await interaction.guild.invites():
                if i.inviter == user:
                    totalInvites += i.uses
            embed = discord.Embed(
                title="Einladungen",
                description=f"Der User {user.mention} hat insgesamt __**{totalInvites}**__ User auf diesen Server eingeladen.",
                colour=discord.Colour.blue()
            )
            embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
            await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(meta(bot))
    bot.tree.add_command(InfoGroup(bot))
    bot.tree.add_command(userinfo_context)