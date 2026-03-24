from pickle import FALSE

import discord
from discord.ext import commands
from discord import app_commands


##########
# TODO(priority:low @Philu risk:low due:2026-04-15 category:AFK-System issue:veraltet): AFK-System auf den neusten stand bringen.

class afk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):

        if message.author.bot:
            return
        if not message.guild:
            return
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                member = message.author
                await cursor.execute(f"SELECT userID FROM afk WHERE guildID = {message.guild.id}")
                result = await cursor.fetchall()
                if result == ():
                    return
                if result:
                    pinguser = result
                    for eintrag in result:
                        memberID = eintrag[0]
                    await cursor.execute(f"SELECT time FROM afk WHERE userID = {memberID}")
                    result3 = await cursor.fetchone()
                    time = result3[0]

                    if len(message.mentions) > 0:
                        member1 = message.mentions[0]

                        if member1.id == int(memberID):
                            await cursor.execute(f"SELECT reason FROM afk WHERE userID = {member1.id}")
                            result1 = await cursor.fetchone()

                            if result1 is None:
                                return
                            else:
                                reason = result1[0]
                                embed = discord.Embed(
                                    description=f'`{member1.name}` ist AFK! Grund: `{reason}`\nEr/Sie ist AFK seit {time}',
                                    color=discord.Colour.blue()
                                )
                                embed.set_author(name=message.author, icon_url=message.author.avatar)
                                embed.set_footer(
                                    text=f"Der User: {member1.name} | UserID: {member1.id} ist AFK")
                                await message.channel.send(message.author.mention, embed=embed)
                    if message.author.id == int(memberID):
                        await cursor.execute(f'SELECT prevName FROM afk WHERE userID = {message.author.id}')
                        result2 = await cursor.fetchone()
                        previous = result2[0]
                        await cursor.execute(
                            f"DELETE FROM afk WHERE userID = {message.author.id} AND guildID = {message.guild.id}")
                        embed = discord.Embed(
                            description=f'Willkommen zurück {message.author.mention}! Du bist nicht mehr AFK!\nDu warst AFK für {time}',
                            color=discord.Colour.blue()
                        )
                        embed.set_footer(
                            text=f"Der User: {message.author.name} | UserID: {message.author.id} ist nicht mehr AFK!")
                        embed.set_author(name=message.author.name, icon_url=message.author.avatar)
                        await message.channel.send(embed=embed)

                        if message.author.id != message.guild.owner_id:
                            try:
                                await message.author.edit(nick=previous, reason='Member removed AFK')
                            except:
                                pass
                            return
                        else:
                            return

    @app_commands.command(name="afk")
    @app_commands.guild_only()
    @app_commands.describe(grund="Warum gehst du genau afk?")
    async def afk(self, interaction: discord.Interaction, grund: str = "AFK"):
        """Setze dich selbst auf AFK!"""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(f"SELECT userID FROM afk WHERE guildID = {interaction.guild.id}")
                result = await cursor.fetchall()
                members = result

                if interaction.user.id not in members:
                    await cursor.execute(
                        f"INSERT INTO afk (guildID, userID, reason, prevName, time) VALUES (%s, %s, %s, %s, %s)",
                        (interaction.guild.id, interaction.user.id, grund, interaction.user.display_name, discord.utils.format_dt(discord.utils.utcnow(), "R")))
                    embed = discord.Embed(
                        description=f'{interaction.user.mention}, du bist nun AFK! Grund: `{grund}`\nDu bist AFK seit {discord.utils.format_dt(discord.utils.utcnow(), "R")}',
                        color=discord.Colour.blue()
                    )
                    embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
                    embed.set_footer(
                        text=f"Der User: {interaction.user.name} | UserID: {interaction.user.id} ist nun AFK")

                    if interaction.user.id != interaction.guild.owner_id:
                        try:
                            await interaction.user.edit(nick='AFK | {}'.format(interaction.user.display_name),
                                                    reason='Member gone AFK')
                        except:
                            pass
                        return await interaction.response.send_message(embed=embed)
                    if interaction.user == interaction.guild.owner:
                        return await interaction.response.send_message(embed=embed)
                    return None

                else:
                    embed = discord.Embed(
                        description=' {}, du bist bereits als AFK makiert!'.format(interaction.user.mention),
                        color=discord.Colour.red()
                    )
                    embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
                    await interaction.response.send_message(embed=embed)
                    return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(afk(bot))