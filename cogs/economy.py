import discord
from discord import app_commands
from discord.ext import commands


class EconomyMixin:
    async def get_user(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT wallet, bank, job, hours_worked, last_work, last_beg, last_rob FROM economy_users WHERE user_id = %s",
                    (user_id,),
                )
                data = await cur.fetchone()

                if not data:
                    await cur.execute(
                        "INSERT INTO economy_users (user_id, wallet, bank, job, hours_worked, last_work, last_beg, last_rob) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, 0, 0, None, 0, None, None, None),
                    )
                    return 0, 0, None, 0, None, None, None

                return data

    async def update_balance(self, user_id: int, wallet_change=0, bank_change=0):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, bank = bank + %s WHERE user_id = %s",
                    (wallet_change, bank_change, user_id),
                )

    async def get_balance(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT wallet, bank FROM economy_users WHERE user_id = %s",
                    (user_id,),
                )
                return await cur.fetchone()


@app_commands.guild_only()
class EconomyGroup(EconomyMixin, app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(name="eco", description="Alles rund um Economy.")

    @app_commands.command(
        name="balance", description="Zeigt deinen aktuellen Kontostand an."
    )
    async def balance(self, interaction: discord.Interaction):
        user_data = await self.get_user(interaction.user.id)
        wallet, bank = user_data[0], user_data[1]
        job_name = user_data[2]
        hours = user_data[3]

        embed = discord.Embed(
            title=f"{interaction.user}'s Kontostand",
            description="> Erhalte Hier Infos über deinen Kontostand und über deinen aktuellen Beruf.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Barvermögen",
            value=f"{wallet} <:Coin:1359178077011181811>",
            inline=True,
        )
        embed.add_field(
            name="Bank", value=f"{bank} <:Coin:1359178077011181811>", inline=True
        )
        embed.add_field(
            name="Beruf",
            value=f"{job_name}, <:Astra_time:1141303932061233202> {hours} Stunden",
            inline=True,
        )
        embed.set_thumbnail(url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="deposit", description="Zahle Geld auf dein Bankkonto ein."
    )
    @app_commands.describe(betrag="Der Betrag, den du einzahlen möchtest.")
    async def deposit(self, interaction: discord.Interaction, betrag: int):
        if betrag <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein.",
                ephemeral=True,
            )
            return

        user_data = await self.get_user(interaction.user.id)
        if user_data[0] < betrag:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast nicht genug Geld in deinem Wallet.",
                ephemeral=True,
            )
            return

        await self.update_balance(interaction.user.id, -betrag, betrag)
        await interaction.response.send_message(
            f"Du hast {betrag} <:Coin:1359178077011181811> auf dein Bankkonto eingezahlt.",
            ephemeral=True,
        )

    @app_commands.command(
        name="withdraw",
        description="Verschiebe Coins von deinem Konto in dein Inventar.",
    )
    @app_commands.describe(betrag="Der Betrag, den du abheben möchtest.")
    async def withdraw(self, interaction: discord.Interaction, betrag: int):
        if betrag <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein.",
                ephemeral=True,
            )
            return

        user_data = await self.get_user(interaction.user.id)
        if user_data[1] < betrag:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast nicht genug Geld auf deinem Bankkonto.",
                ephemeral=True,
            )
            return

        await self.update_balance(interaction.user.id, betrag, -betrag)
        await interaction.response.send_message(
            f"Du hast {betrag} <:Coin:1359178077011181811> von deinem Bankkonto abgehoben."
        )

    @app_commands.command(
        name="leaderboard", description="Zeige die reichsten Spieler."
    )
    @app_commands.describe(
        scope="Wähle, ob die globale oder serverbezogene Rangliste angezeigt wird."
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="global", value="global"),
            app_commands.Choice(name="server", value="server"),
        ]
    )
    async def leaderboard(self, interaction: discord.Interaction, scope: str):
        try:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    if scope == "global":
                        await cur.execute("""
                            SELECT user_id, wallet + bank AS gesamt
                            FROM economy_users
                            ORDER BY gesamt DESC
                            LIMIT 10
                            """)
                        top_users = await cur.fetchall()
                    else:
                        member_ids = [
                            member.id
                            for member in interaction.guild.members
                            if not member.bot
                        ]
                        if not member_ids:
                            await interaction.response.send_message(
                                "Keine Benutzer gefunden.", ephemeral=True
                            )
                            return

                        placeholders = ",".join(["%s"] * len(member_ids))
                        query = f"""
                            SELECT user_id, wallet + bank AS gesamt
                            FROM economy_users
                            WHERE user_id IN ({placeholders})
                            ORDER BY gesamt DESC
                            LIMIT 10
                        """
                        await cur.execute(query, tuple(member_ids))
                        top_users = await cur.fetchall()

            if not top_users:
                await interaction.response.send_message(
                    "Es wurden keine Benutzer gefunden oder die Rangliste ist leer."
                )
                return

            embed = discord.Embed(
                title=(
                    "<:Astra_users:1141303946602872872> Rangliste (Global)"
                    if scope == "global"
                    else f"<:Astra_users:1141303946602872872> Rangliste ({interaction.guild.name})"
                ),
                color=discord.Color.blue(),
            )

            for i, (user_id, gesamt) in enumerate(top_users, start=1):
                user = self.bot.get_user(user_id)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except Exception:
                        user = None

                name = user.name if user else f"Unbekannt ({user_id})"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"{gesamt} <:Coin:1359178077011181811>",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)
        except Exception as error:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Fehler beim Abrufen der Rangliste: {error}",
                ephemeral=True,
            )
            print(f"Leaderboard Error: {error}")


class Economy(EconomyMixin, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None

    @commands.command(name="unlockjobs")
    @commands.is_owner()
    async def unlock_jobs(self, ctx, user: discord.User, max_hours: int):
        if max_hours < 0:
            await ctx.send("<:Astra_x:1141303954555289600> Ungültiger Wert.")
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM economy_users WHERE user_id=%s", (user.id,)
                )
                row = await cur.fetchone()
                if not row:
                    await cur.execute(
                        "INSERT INTO economy_users (user_id, hours_worked) VALUES (%s, %s)",
                        (user.id, max_hours),
                    )
                else:
                    await cur.execute(
                        "UPDATE economy_users SET hours_worked = %s WHERE user_id=%s",
                        (max_hours, user.id),
                    )

        await ctx.send(
            f"<:Astra_accept:1141303821176422460> {user.mention} wurden alle Jobs bis **{max_hours} Stunden** freigeschaltet!"
        )

    @commands.command(
        name="addcoins",
        description="Füge einem Nutzer <:Coin:1359178077011181811> hinzu (Nur für Botbesitzer).",
    )
    @commands.is_owner()
    async def addcoins(
        self, ctx, user: discord.User, betrag: int, balance_type: str = "wallet"
    ):
        if betrag <= 0:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Betrag.")
            return

        if balance_type not in ["wallet", "bank"]:
            await ctx.channel.send(
                "<:Astra_x:1141303954555289600> Ungültiger Balance-Typ. Verwende `wallet` oder `bank`."
            )
            return

        await self.get_balance(user.id)
        await self.update_balance(
            user.id,
            wallet_change=betrag if balance_type == "wallet" else 0,
            bank_change=betrag if balance_type == "bank" else 0,
        )
        await ctx.channel.send(
            f"<:Astra_accept:1141303821176422460> {betrag} <:Coin:1359178077011181811> wurden {user.mention} zu {balance_type} hinzugefügt."
        )

    @commands.command(
        name="removecoins",
        description="Entferne einem Nutzer <:Coin:1359178077011181811> (Nur für Botbesitzer).",
    )
    @commands.is_owner()
    async def removecoins(
        self, ctx, user: discord.User, betrag: int, balance_type: str = "wallet"
    ):
        if betrag <= 0:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Betrag.")
            return

        if balance_type not in ["wallet", "bank"]:
            await ctx.channel.send(
                "<:Astra_x:1141303954555289600> Ungültiger Balance-Typ. Verwende `wallet` oder `bank`."
            )
            return

        user_data = await self.get_balance(user.id)
        current_balance = user_data[0] if balance_type == "wallet" else user_data[1]
        if current_balance < betrag:
            await ctx.channel.send(
                f"<:Astra_x:1141303954555289600> {user.mention} hat nicht genug {balance_type} um {betrag} zu entfernen."
            )
            return

        await self.update_balance(
            user.id,
            wallet_change=-betrag if balance_type == "wallet" else 0,
            bank_change=-betrag if balance_type == "bank" else 0,
        )
        await ctx.channel.send(
            f"<:Astra_accept:1141303821176422460> {betrag} <:Coin:1359178077011181811> wurden {user.mention} von {balance_type} entfernt."
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
    bot.tree.add_command(EconomyGroup(bot))
