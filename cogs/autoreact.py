import discord
from discord.ext import commands
from discord import app_commands
from discord.app_commands import Group
from typing import Literal

##########


class autoreact(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg):
        if not msg.guild:
            return
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"SELECT channelID FROM autoreact WHERE guildID = {msg.guild.id}")

                result = await cursor.fetchall()

                if result is None:
                    return
                else:

                    for eintrag in result:
                        channelID = eintrag[0]
                        if msg.channel.id == channelID:
                            await cursor.execute("SELECT emoji FROM autoreact WHERE channelID = (%s)", (msg.channel.id,))
                            emoji = await cursor.fetchone()
                            if emoji:
                                emoji3 = emoji[0]
                                try:
                                    await msg.add_reaction(emoji3)
                                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                                    pass

    @app_commands.command(name="autoreact")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(channel="Textchannel", emoji="Emoji")
    async def add(self, interaction: discord.Interaction, modus: Literal['Einschalten', 'Ausschalten', 'Anzeigen'], channel: discord.TextChannel, emoji: str):
        """Richte Auto Reaktionen in Channels ein."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if modus == "Einschalten":
                    await cursor.execute("INSERT INTO autoreact (guildID, channelID, emoji) VALUES (%s, %s, %s)",
                                         (interaction.guild.id, channel.id, emoji))

                    await cursor.execute(f"SELECT channelID FROM autoreact WHERE channelID = {channel.id}")
                    wel = await cursor.fetchone()
                    channelID = wel[0]

                    ch = interaction.guild.get_channel(channelID)

                    await cursor.execute("SELECT emoji FROM autoreact WHERE channelID = (%s)", (ch.id))
                    emoji = await cursor.fetchone()
                    emoji3 = emoji[0]

                    embed = discord.Embed(title="Eintrag erstellt",
                                          description=f"Einstellungen:",
                                          color=discord.Color.green())
                    embed.add_field(name="Channel", value=ch.mention, inline=False)
                    embed.add_field(name="Emoji", value=emoji3, inline=False)
                    await interaction.response.send_message(embed=embed)
                    
                if modus == "Ausschalten":
                    await cursor.execute("SELECT channelID FROM autoreact WHERE guildID = (%s)", (interaction.guild.id))
                    result = await cursor.fetchall()
                    if result:
                        for eintrag in result:
                            channelID = eintrag[0]
                            print(channelID)
                            if channel.id == channelID:
                                await cursor.execute("DELETE FROM autoreact WHERE channelID = (%s)", (channel.id))
                                await interaction.response.send_message("✔ Einträge gelöscht!", ephemeral=True)
                    if not result:
                        await interaction.response.send_message("❌ Kein Autoreact aktiv in diesem Kanal.", ephemeral=True)
                
                if modus == "Anzeigen":
                    await cursor.execute(f"SELECT channelID, emoji FROM autoreact WHERE guildID = {interaction.guild.id}")
                    result = await cursor.fetchall()
                    if not result:
                        await interaction.response.send_message("Keine Einträge vorhanden!", ephemeral=True)
                    if result:

                        embed = discord.Embed(title="Aktuelle Einträge",
                                              description=f"Einstellungen:",
                                              color=discord.Color.green())

                        for eintrag in result:
                            channelID = eintrag[0]
                            emoji3 = eintrag[1]

                            try:
                                print(channelID)
                                ch = interaction.guild.get_channel(int(channelID))
                            except:
                                await interaction.response.send_message("Autoreact ist deaktiviert.", ephemeral=True)

                            embed.add_field(name=ch.mention, value=emoji3, inline=True)

                        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(autoreact(bot))