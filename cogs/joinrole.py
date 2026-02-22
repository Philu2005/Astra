import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal


##########
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


async def timeline(seconds):
    result = []
    intervals = (
        ('Weeks', 604800),
        ('Days', 86400),
        ('Hours', 3600),
        ('Minutes', 60),
        ('Seconds', 1),
    )

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(int(value), name))
    return ', '.join(result)


class joinrole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT roleID FROM joinrole WHERE guildID = %s",
                    (member.guild.id,)
                )
                result = await cursor.fetchone()

        if result is None:
            return

        role = discord.utils.get(member.guild.roles, id=int(result[0]))
        if role is None:
            return

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            print("Bot-Rolle ist nicht hoch genug.")
        except Exception as e:
            print(f"Joinrole Fehler: {e}")

    @app_commands.command(name="joinrole", description="Verwalte die Joinrolle für neue Mitglieder auf diesem Server.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.describe(argument="Aktion auswählen: 'Einschalten', 'Ausschalten' oder 'Anzeigen'.", role="Die Rolle, die neuen Mitgliedern automatisch zugewiesen werden soll (nur bei 'Einschalten' nötig).")
    async def joinrole(self, interaction: discord.Interaction, argument: Literal['Einschalten', 'Ausschalten', 'Anzeigen'], role: discord.Role = None):
        """Lege eine Joinrolle für deinen Server fest."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                if interaction.user.bot:
                    return

                if argument == "Einschalten":

                    if role is None:
                        await interaction.response.send_message("Du musst eine Rolle angeben.", ephemeral=True)
                        return

                    if role >= interaction.guild.me.top_role:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Diese Rolle ist höher oder gleich meiner Rolle.\n"
                            "Bitte ziehe meine Rolle in den Servereinstellungen über diese Rolle.",
                            ephemeral=True
                        )
                        return

                    if role.is_default():
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Die @everyone Rolle kann nicht als Joinrole gesetzt werden.",
                            ephemeral=True
                        )
                        return

                    await cursor.execute(
                        "SELECT roleID FROM joinrole WHERE guildID = %s",
                        (interaction.guild.id,)
                    )
                    result = await cursor.fetchone()

                    if result is None:
                        await cursor.execute(
                            "INSERT INTO joinrole (roleID, guildID) VALUES (%s, %s)",
                            (role.id, interaction.guild.id)
                        )
                        text = f"**Joinrole aktiviert**\n\nNeue Mitglieder erhalten nun automatisch {role.mention}."
                    else:
                        await cursor.execute(
                            "UPDATE joinrole SET roleID = %s WHERE guildID = %s",
                            (role.id, interaction.guild.id)
                        )
                        text = f"**Joinrole aktualisiert**\n\nNeue Mitglieder erhalten nun {role.mention}."

                    await conn.commit()

                    embed = discord.Embed(
                        colour=discord.Colour.blurple(),
                        description=text
                    )
                    embed.set_author(
                        name="Joinrole-System",
                        icon_url=self.bot.user.display_avatar.url
                    )
                    embed.set_footer(
                        text=f"Ausgeführt von {interaction.user}",
                        icon_url=interaction.user.display_avatar.url
                    )

                    await interaction.response.send_message(embed=embed)

                if argument == "Ausschalten":

                    await cursor.execute(
                        "SELECT roleID FROM joinrole WHERE guildID = %s",
                        (interaction.guild.id,)
                    )
                    result = await cursor.fetchone()

                    if result is None:
                        await interaction.response.send_message("Keine Joinrole gesetzt.", ephemeral=True)
                        return

                    await cursor.execute(
                        "DELETE FROM joinrole WHERE guildID = %s",
                        (interaction.guild.id,)
                    )

                    await conn.commit()

                    embed = discord.Embed(
                        colour=discord.Colour.blurple(),
                        description="**Joinrole deaktiviert**\n\nNeue Mitglieder erhalten keine automatische Rolle mehr."
                    )
                    embed.set_author(
                        name="Joinrole-System",
                        icon_url=self.bot.user.display_avatar.url
                    )
                    embed.set_footer(
                        text=f"Ausgeführt von {interaction.user}",
                        icon_url=interaction.user.display_avatar.url
                    )

                    await interaction.response.send_message(embed=embed)

                if argument == "Anzeigen":

                    await cursor.execute(
                        "SELECT roleID FROM joinrole WHERE guildID = %s",
                        (interaction.guild.id,)
                    )
                    result = await cursor.fetchone()

                    if result is None:
                        await interaction.response.send_message("Keine Joinrole gesetzt.", ephemeral=True)
                        return

                    roless = discord.utils.get(interaction.guild.roles, id=int(result[0]))

                    if roless is None:
                        await interaction.response.send_message("Gespeicherte Rolle existiert nicht mehr.", ephemeral=True)
                        return

                    embed = discord.Embed(
                        colour=discord.Colour.blurple(),
                        description=f"**Aktive Joinrole**\n\nNeue Mitglieder erhalten automatisch {roless.mention}."
                    )
                    embed.set_author(
                        name="Joinrole-System",
                        icon_url=self.bot.user.display_avatar.url
                    )
                    embed.set_footer(
                        text=f"Abgerufen von {interaction.user}",
                        icon_url=interaction.user.display_avatar.url
                    )

                    await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(joinrole(bot))