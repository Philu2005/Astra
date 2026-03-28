import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone


class afk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 🔹 SAFE DATETIME CONVERTER (FIXED WITH UTC)
    def _safe_dt(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value

        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except:
                return discord.utils.utcnow()

        return discord.utils.utcnow()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot or not message.guild:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # 🔹 Alle AFK User holen (eine Query)
                await cursor.execute(
                    "SELECT userID, reason, time, prevName FROM afk WHERE guildID = %s",
                    (message.guild.id,)
                )
                rows = await cursor.fetchall()

                if not rows:
                    return

                # 🔹 Dict bauen + Zeit fixen
                afk_users = {
                    row[0]: {
                        "reason": row[1],
                        "time": self._safe_dt(row[2]),
                        "prev": row[3]
                    }
                    for row in rows
                }

                # =========================
                # 🔔 MENTIONS CHECK
                # =========================
                for user in message.mentions:
                    if user.id in afk_users:
                        data = afk_users[user.id]

                        embed = discord.Embed(
                            description=(
                                f"### <:Astra_mic_off:1141824920809132122> {user.mention} ist aktuell AFK\n\n"
                                f"**Grund:** {data['reason']}\n"
                                f"<:Astra_time:1141303932061233202> Seit {discord.utils.format_dt(data['time'], 'R')}"
                            ),
                            color=discord.Color.blue()
                        )

                        embed.set_author(
                            name=f"{user.display_name} ist AFK",
                            icon_url=user.display_avatar
                        )

                        embed.set_footer(
                            text=f"Erwähnt von {message.author.display_name}",
                            icon_url=message.author.display_avatar
                        )

                        await message.reply(
                            embed=embed,
                            mention_author=True
                        )

                # =========================
                # 👋 AFK ENTFERNEN
                # =========================
                if message.author.id in afk_users:
                    data = afk_users[message.author.id]

                    await cursor.execute(
                        "DELETE FROM afk WHERE userID = %s AND guildID = %s",
                        (message.author.id, message.guild.id)
                    )

                    embed = discord.Embed(
                        description=(
                            f"### 👋 Willkommen zurück!\n\n"
                            f"{message.author.mention}, du bist nicht mehr AFK\n"
                            f"<:Astra_time:1141303932061233202> AFK seit {discord.utils.format_dt(data['time'], 'R')}"
                        ),
                        color=discord.Color.blue()
                    )

                    embed.set_author(
                        name=message.author.display_name,
                        icon_url=message.author.display_avatar
                    )

                    await message.channel.send(embed=embed)

                    # Nick zurücksetzen
                    if message.author.id != message.guild.owner_id:
                        try:
                            await message.author.edit(
                                nick=data["prev"],
                                reason="AFK entfernt"
                            )
                        except:
                            pass

    # =========================
    # 💤 AFK COMMAND
    # =========================
    @app_commands.command(name="afk")
    @app_commands.guild_only()
    @app_commands.describe(grund="Warum gehst du genau AFK?")
    async def afk(self, interaction: discord.Interaction, grund: str = "AFK"):

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # 🔹 Check ob schon AFK
                await cursor.execute(
                    "SELECT 1 FROM afk WHERE userID = %s AND guildID = %s",
                    (interaction.user.id, interaction.guild.id)
                )

                if await cursor.fetchone():
                    embed = discord.Embed(
                        description=f"{interaction.user.mention}, du bist bereits AFK!",
                        color=discord.Colour.red()
                    )
                    embed.set_author(
                        name=interaction.user.name,
                        icon_url=interaction.user.display_avatar
                    )

                    return await interaction.response.send_message(
                        embed=embed,
                        ephemeral=True
                    )

                now = discord.utils.utcnow()

                # 🔹 AFK setzen
                await cursor.execute(
                    """
                    INSERT INTO afk (guildID, userID, reason, prevName, time)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        interaction.guild.id,
                        interaction.user.id,
                        grund,
                        interaction.user.display_name,
                        now
                    )
                )

                embed = discord.Embed(
                    description=(
                        f"### <:Astra_mic_off:1141824920809132122> Du bist jetzt AFK\n\n"
                        f"**Grund:** {grund}\n"
                        f"<:Astra_time:1141303932061233202> Seit {discord.utils.format_dt(now, 'R')}"
                    ),
                    color=discord.Color.blue()
                )

                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar
                )
                embed.set_footer(
                    text=f"UserID: {interaction.user.id}"
                )

                # Nick setzen
                if interaction.user.id != interaction.guild.owner_id:
                    try:
                        await interaction.user.edit(
                            nick=f"AFK | {interaction.user.display_name}",
                            reason="AFK gesetzt"
                        )
                    except:
                        pass

                await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(afk(bot))