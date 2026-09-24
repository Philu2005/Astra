import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
import random
import json


async def get_bank_data():
    with open('mainbank.json', 'r') as f:
        users = json.load(f)

    return users


async def update_bank(user, change=0, mode='wallet'):
    users = await get_bank_data()

    users[str(user.id)][mode] += change

    with open('mainbank.json', 'w') as f:
        json.dump(users, f, indent=4)
    bal = users[str(user.id)]['wallet'], users[str(user.id)]['bank']
    return bal


##########


class guessthenumber(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author.bot:
            return
        if not msg.guild:
            return
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT channelID FROM guessthenumber WHERE guildID = (%s)", (msg.guild.id))
                result = await cursor.fetchone()
                if not result:
                    return
                else:
                    channelid = result[0]
                    if msg.channel.id != channelid:
                        return
                    await cursor.execute("SELECT number FROM guessthenumber WHERE channelID = (%s)", (channelid,))
                    result2 = await cursor.fetchone()
                    if not result2:
                        return
                    number1 = result2[0]
                    if str(number1) == msg.content:
                        number = random.randint(30, 100)
                        number2 = random.randint(1, number)
                        channel = self.bot.get_channel(channelid)
                        await cursor.execute("UPDATE guessthenumber SET number = (%s) WHERE guildID = (%s)", (number2, msg.guild.id))
                        embed = discord.Embed(title="Guess the number",
                                              description=f"Ich habe eine Nummer zwischen **1** und **{number}** gewählt. Kannst du sie erraten?",
                                              colour=discord.Colour.blue(), timestamp=discord.utils.utcnow())
                        embed.set_footer(text=f"Die letzte Nummer wurde von {msg.author} erraten.", icon_url=msg.author.avatar)
                        won = self.bot.get_emoji(1141319026140790885)
                        if won:
                            try:
                                await msg.add_reaction(won)
                            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                                pass
                        if channel:
                            try:
                                await channel.send(f"{msg.author.mention} hat die Nummer erraten.", embed=embed)
                            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                                pass
                        else:
                            pass

    @app_commands.command(name="guessthenumber", description="Minispiel ‚Guess the Number‘ auf deinem Server verwalten.")
    @app_commands.describe(modus="Wähle 'Einschalten', um das Spiel zu starten, oder 'Ausschalten', um es zu beenden.", kanal="Der Kanal, in dem das Spiel stattfinden soll.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_channels=True)
    async def guessthenumber(
            self,
            interaction: discord.Interaction,
            modus: Literal['Einschalten', 'Ausschalten'],
            kanal: discord.TextChannel
    ):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if modus == "Einschalten":
                    await cursor.execute("SELECT channelID FROM guessthenumber WHERE guildID = (%s)", interaction.guild.id)
                    result = await cursor.fetchone()
                    if result:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Guess the number ist bereits für diesem Server aktiviert.**")
                    if not result:
                        number = random.randint(30, 100)
                        number2 = random.randint(1, number)
                        await cursor.execute("INSERT INTO guessthenumber (guildID, channelID, number) VALUES (%s, %s, %s)",
                                             (interaction.guild.id, kanal.id, number2))
                        embed = discord.Embed(title="Guess the number",
                                                      description=f"Ich habe eine Nummer zwischen **1** und **{number}** gewählt. Kannst du sie erraten?",
                                                      colour=discord.Colour.blue(), timestamp=discord.utils.utcnow())
                        await interaction.response.send_message(embed=embed)
                if modus == "Ausschalten":
                    await cursor.execute("SELECT channelID FROM guessthenumber WHERE guildID = (%s)", interaction.guild.id)
                    result = await cursor.fetchone()
                    if not result:
                        await interaction.response.send_message("<:Astra_x:1141303954555289600> **Guess the number ist nicht in diesem Server aktiviert.**")
                    if result:
                        await cursor.execute("DELETE FROM guessthenumber WHERE guildID = (%s)", interaction.guild.id)
                        await interaction.response.send_message("<:Astra_accept:1141303821176422460> **Das Guessthenumber Minispiel ist nun für diesen Server deaktiviert.**")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(guessthenumber(bot))
