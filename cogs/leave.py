import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
import random

from utils.branding import get_current_colour


##########

def random_color():
    return discord.Color.from_rgb(random.randint(1, 255), random.randint(1, 255), random.randint(1, 255))


class Leave(discord.ui.Modal, title="Set your Leave message!"):
    def __init__(self, bot: commands.Bot, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel
        self.bot = bot

    name = discord.ui.TextInput(
        label='Text',
        style=discord.TextStyle.long,
        placeholder='%member-Member#0000  | %name-Member  | %mention-@Member | %guild-Severname | %usercount-Memberanzahl',
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute("INSERT INTO leavemsg (guildID, channelID, msg) VALUES (%s, %s, %s)", (interaction.guild.id, self.channel.id, self.name.value))

                    embed1 = discord.Embed(title="Leave Nachricht gesetzt.",
                                           description=f"Die Leave Nachricht findet statt in: {self.channel.mention}.\nNachricht: {self.name.value}.",
                                           color=get_current_colour())
                    await interaction.response.send_message(embed=embed1)
                except:
                    await cursor.execute(f"SELECT channelID FROM leavemsg WHERE guildID = (%s)", interaction.guild.id)
                    wel = await cursor.fetchone()
                    await cursor.execute(f"SELECT msg FROM leavemsg WHERE guildID = (%s)", interaction.guild.id)
                    come = await cursor.fetchone()

                    try:
                        ch = interaction.guild.get_channel(int(wel[0]))
                    except:
                        return

                    embed = discord.Embed(title="Leave Nachricht",
                                          description=f"Leave Nachrichten bereits aktiv. Um die Nachricht zu ändern nutze `/leavemsg`.",
                                          color=discord.Color.red())
                    embed.add_field(name="Kanal", value=ch, inline=False)
                    embed.add_field(name="Nachricht", value=come[0], inline=False)
                    await interaction.response.send_message(embed=embed)


class leave(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"SELECT channelID FROM leavemsg WHERE guildID = (%s)", member.guild.id)
                channel = await cursor.fetchone()
                await cursor.execute(f"SELECT msg FROM leavemsg WHERE guildID = (%s)", member.guild.id)
                message = await cursor.fetchone()
                if channel is None and message is None:
                    return
                else:
                    try:
                        ch = member.guild.get_channel(int(channel[0]))
                    except:
                        return
                    finalmsg = message[0].replace("%member", str(member)).replace("%name", str(member.name)).replace(
                        "%mention", str(member.mention)).replace("%guild", str(member.guild)).replace("%usercount",
                                                                                                      str(member.guild.member_count))
                    embed = discord.Embed(description=finalmsg, color=random_color())
                    try:
                        await ch.send(embed=embed)
                    except:
                        pass
                    return

    @app_commands.command(name="testleave", description="Simuliere, dass du den Server verlässt, um Leave-Nachrichten oder Logs zu testen.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testleave(self, interaction: discord.Interaction):
        """Schaue ob deine Leavemsg gut funktioniert."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                member = interaction.user
                await cursor.execute(f"SELECT channelID FROM leavemsg WHERE guildID = (%s)", member.guild.id)
                channel = await cursor.fetchone()
                await cursor.execute(f"SELECT msg FROM leavemsg WHERE guildID = (%s)", member.guild.id)
                message = await cursor.fetchone()
                if channel is None and message is None:
                    embed = discord.Embed(
                        description=f"Die Leave Nachrichten sind deaktiviert. Füge eine mit `/leavemsg` hinzu.",
                        color=discord.Color.red())
                    await interaction.response.send_message(embed=embed)
                    return
                else:
                    try:
                        ch = interaction.guild.get_channel(int(channel[0]))
                    except:
                        return
                    finalmsg = message[0].replace("%member", str(member)).replace("%name", str(member.name)).replace(
                        "%mention",
                        str(member.mention)).replace(
                        "%guild", str(member.guild)).replace("%usercount", str(member.guild.member_count))
                    embed = discord.Embed(description=finalmsg, color=random_color())
                    embed.set_footer(text=f"Testleave von {member}")
                    try:
                        await ch.send(embed=embed)
                        await interaction.response.send_message(f"Testleave Nachricht in {ch.mention} gesendet.")
                    except:
                        pass
                    return

    @app_commands.command(name="leavemsg", description="Lege eine Nachricht fest für User, die den Server verlassen.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(argument="Aktion auswählen: 'Einschalten', 'Ausschalten' oder 'Anzeigen'.", channel="Kanal, in dem die Nachricht gesendet werden soll (nur bei 'Einschalten' nötig).")
    async def leavemsg(self, interaction: discord.Interaction, argument: Literal['Einschalten', 'Ausschalten', 'Anzeigen'], channel: discord.TextChannel = None):
        """Legt fest, ob und wo eine Nachricht beim Serververlassen eines Mitglieds gesendet wird."""
        if argument == "Einschalten":
            await interaction.response.send_modal(Leave(channel=channel, bot=self.bot))
        if argument == "Ausschalten":
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(f"SELECT channelID FROM leavemsg WHERE guildID = (%s)", interaction.guild.id)
                    result = await cursor.fetchone()
                    if result is None:
                        return
                    if result is not None:
                        channelID = result
                        if (channel.id,) == channelID:
                            await cursor.execute(
                                f"DELETE FROM leavemsg WHERE channelID = (%s) AND guildID = (%s)", (channel.id, interaction.guild.id))
                            await interaction.response.send_message("<:Astra_accept:1141303821176422460> **Leave Nachrichten deaktiviert.**", ephemeral=True)
                        else:
                            await interaction.response.send_message("<:Astra_x:1141303954555289600> **Die Leave Nachrichten sind bereits deaktiviert.**",
                                                                    ephemeral=True)
                            return
        if argument == "Anzeigen":
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(f"SELECT channelID FROM leavemsg WHERE guildID = (%s)", interaction.guild.id)
                    wel = await cursor.fetchone()
                    await cursor.execute(f"SELECT msg FROM leavemsg WHERE guildID = (%s)", interaction.guild.id)
                    come = await cursor.fetchone()

                    try:
                        ch = interaction.guild.get_channel(int(wel[0]))
                    except:
                        return

                    embed = discord.Embed(title="Leave Nachricht",
                                          description=f"Leave Nachrichten bereits aktiv. Um die Nachricht zu ändern nutze `/leavemsg`.",
                                          color=discord.Color.red())
                    embed.add_field(name="Kanal", value=ch, inline=False)
                    embed.add_field(name="Nachricht", value=come[0], inline=False)
                    await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(leave(bot))
