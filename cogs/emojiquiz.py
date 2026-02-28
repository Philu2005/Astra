import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
import json
import random
import re
import unicodedata
import difflib

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_user(self, user_id: int):
        """Holt den Benutzer aus der Datenbank."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM economy_users WHERE user_id = %s", (user_id,))
                data = await cur.fetchone()
                if not data:
                    await cur.execute("INSERT INTO economy_users (user_id) VALUES (%s)", (user_id,))
                    return user_id, 0, 0, None, 0, None  # Falls der Benutzer nicht existiert, wird er erstellt
                return data

    async def update_balance(self, user_id: int, wallet_change=0, bank_change=0):
        """Aktualisiert das Wallet und/oder Bankguthaben des Benutzers."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, bank = bank + %s WHERE user_id = %s",
                    (wallet_change, bank_change, user_id)
                )

    async def get_balance(self, user_id: int):
        """Holt das Wallet- und Bankguthaben des Benutzers."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT wallet, bank FROM economy_users WHERE user_id = %s", (user_id,))
                return await cur.fetchone()


class buttons_emj(discord.ui.View):
    def __init__(self, bot, economy):
        super().__init__(timeout=None)
        self.bot = bot
        self.economy = economy

    @discord.ui.button(label='Skip', style=discord.ButtonStyle.grey, custom_id='persistent_view:skip', emoji="<:Astra_arrow:1141303823600717885>")
    async def skip(self, interaction: discord.Interaction, button: discord.Button):
        import asyncio
        try:
            # Sofort defern, damit Discord keine Zeitüberschreitung meldet
            await interaction.response.defer(ephemeral=True)

            async with interaction.client.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT channelID, messageID FROM emojiquiz WHERE guildID = (%s)",
                                      (interaction.guild.id,))
                    already_on = await cur.fetchone()
                    if not already_on:
                        await interaction.followup.send(
                            "<:Astra_x:1141303954555289600> Das Emojiquizz ist deaktiviert.")
                        return

                    user_balance = await self.economy.get_balance(interaction.user.id)
                    wallet, bank = user_balance
                    if wallet < 20:
                        await interaction.followup.send(
                            "Du hast nicht genug Geld, um das Quiz zu überspringen. Du benötigst mindestens 20 <:Astra_cookie:1141303831293079633>.",
                            ephemeral=True)
                        return

                    # Hole alte Lösung bevor sie gelöscht wird
                    await cur.execute("SELECT lösung FROM emojiquiz_lsg WHERE guildID = %s", (interaction.guild.id,))
                    old_solution_data = await cur.fetchone()
                    old_solution = old_solution_data[0] if old_solution_data else "Unbekannt"

                    # Ziehe Geld ab
                    await self.economy.update_balance(interaction.user.id, wallet_change=-20)

                    # Nachricht posten, dass geskippt wurde (wird später gelöscht)
                    skipped_msg = await interaction.channel.send(
                        f"{interaction.user.mention} hat das Wort übersprungen. Das Wort war: **{old_solution}**. (-20 <:Astra_cookie:1141303831293079633>)"
                    )

                    # 2 Sekunden warten
                    await asyncio.sleep(2)

                    # Alle User-Messages im Channel löschen
                    await cur.execute(
                        "SELECT messageID FROM emojiquiz_messages WHERE guildID = %s AND channelID = %s",
                        (interaction.guild.id, interaction.channel.id)
                    )
                    all_msg_ids = await cur.fetchall()
                    for (mid,) in all_msg_ids:
                        try:
                            m = await interaction.channel.fetch_message(mid)
                            await m.delete()
                        except Exception:
                            pass

                    # Tabelle leeren
                    await cur.execute(
                        "DELETE FROM emojiquiz_messages WHERE guildID = %s AND channelID = %s",
                        (interaction.guild.id, interaction.channel.id)
                    )

                    # Übersprungene Info-Nachricht löschen
                    try:
                        await skipped_msg.delete()
                    except Exception:
                        pass

                    # Alte Quiznachricht löschen
                    channel_id, old_message_id = already_on
                    try:
                        quiz_channel = self.bot.get_channel(channel_id)
                        if quiz_channel and old_message_id:
                            msg = await quiz_channel.fetch_message(old_message_id)
                            await msg.delete()
                    except Exception:
                        pass

                    # Alte Lösung löschen
                    await cur.execute("DELETE FROM emojiquiz_lsg WHERE guildID = (%s)", (interaction.guild.id,))

                    # Neue Frage holen
                    query = "SELECT question, answer, hint FROM emojiquiz_quizzez ORDER BY RAND() LIMIT 1;"
                    await cur.execute(query)
                    quiz_data = await cur.fetchone()
                    if quiz_data:
                        question, answer, hint = quiz_data
                        emojiquiz_embed = discord.Embed(
                            title="Emojiquiz",
                            description="Solltest du Probleme beim Lösen haben, kannst du die Buttons dieser Nachricht benutzen.",
                            colour=discord.Colour.blue())
                        emojiquiz_embed.add_field(name="<:Astra_support:1141303923752325210>  Gesuchter Begriff", value=question, inline=True)
                        emojiquiz_embed.add_field(name="<:Astra_wichtig:1141303951862534224>  Tipp", value=f"||{hint}||", inline=True)
                        emojiquiz_embed.set_footer(
                            text=f"The last Quiz was skipped by {interaction.user.name}",
                            icon_url=interaction.user.avatar)

                        sent = await interaction.channel.send(
                            embed=emojiquiz_embed,
                            view=buttons_emj(bot=self.bot, economy=self.economy)
                        )
                        await cur.execute("UPDATE emojiquiz SET messageID = %s WHERE guildID = %s",
                                          (sent.id, interaction.guild.id))
                        await cur.execute("INSERT INTO emojiquiz_lsg(guildID, lösung) VALUES (%s, %s)",
                                          (interaction.guild.id, answer))
        except discord.errors.NotFound:
            print(f"Die Interaktion von {interaction.user} ist abgelaufen oder bereits beantwortet.")


    @discord.ui.button(label='Initial letter', style=discord.ButtonStyle.grey, custom_id='persistent_view:tip', emoji="<:Astra_light_on:1141303864134467675>")
    async def tip(self, interaction: discord.Interaction, button: discord.Button):
        async with interaction.client.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT channelID FROM emojiquiz WHERE guildID = (%s)", (interaction.guild.id,))
                already_on = await cur.fetchone()
                if not already_on:
                    await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> Das Emojiquizz ist deaktiviert.")
                    return
                await cur.execute("SELECT lösung FROM emojiquiz_lsg WHERE guildID = (%s)", (interaction.guild.id,))
                lsg = await cur.fetchone()
                loesung = lsg[0]
                words = loesung.split()

                user_balance = await self.economy.get_balance(interaction.user.id)
                wallet, bank = user_balance
                if wallet < 20:
                    await interaction.response.send_message(
                        "Du hast nicht genug Geld, um den Tipp zu erhalten. Du benötigst mindestens 20 <:Astra_cookie:1141303831293079633>.",
                        ephemeral=True)
                    return

                first_letter = words[0][0]
                await self.economy.update_balance(interaction.user.id, wallet_change=-20)
                await interaction.response.send_message(
                    f"💡 Der erste Buchstabe für das Wort was du suchst ist: {first_letter}. Aber mehr Tipps kann ich dir nicht geben.",
                    ephemeral=True)



class emojiquiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.economy = Economy(bot)  # Füge die Economy-Instanz hinzu

    @commands.Cog.listener()
    async def on_message(self, msg):
        if not msg.guild or msg.author.bot:
            return

        def normalize_text(text: str) -> str:
            text = text.lower().strip()

            # Umlaute normalisieren
            text = unicodedata.normalize("NFKD", text)
            text = "".join(c for c in text if not unicodedata.combining(c))

            # Sonderzeichen entfernen
            text = re.sub(r"[^a-z0-9 ]", "", text)

            # Mehrere Leerzeichen entfernen
            text = re.sub(r"\s+", " ", text).strip()

            return text

        def remove_leading_article(text: str) -> str:
            return re.sub(r"^(der|die|das|ein|eine)\s+", "", text)

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Ist Emojiquiz aktiv?
                await cur.execute("SELECT channelID, messageID FROM emojiquiz WHERE guildID = %s", (msg.guild.id,))
                already_on = await cur.fetchone()
                if not already_on:
                    return

                channelID, quiz_message_id = already_on

                # Ist das der richtige Channel?
                if int(channelID) == int(msg.channel.id):

                    # Jede Usernachricht merken
                    await cur.execute(
                        "INSERT INTO emojiquiz_messages (guildID, channelID, messageID) VALUES (%s, %s, %s)",
                        (msg.guild.id, msg.channel.id, msg.id)
                    )

                    # Lösung holen
                    await cur.execute("SELECT lösung FROM emojiquiz_lsg WHERE guildID = %s", (msg.guild.id,))
                    result2 = await cur.fetchone()
                    if not result2:
                        return

                    loesung = result2[0]

                    user_input_raw = msg.content.strip()
                    solution_raw = loesung.strip()

                    user_input = normalize_text(user_input_raw)
                    correct_answer = normalize_text(solution_raw)

                    # Variante ohne führenden Artikel (nur prüfen, nicht verändern)
                    correct_without_article = normalize_text(remove_leading_article(solution_raw))

                    correct = False

                    # 1️⃣ Exakter Match
                    if user_input == correct_answer:
                        correct = True

                    # 2️⃣ Match ohne Artikel (User schreibt nur "Eiskönigin")
                    elif user_input == correct_without_article:
                        correct = True

                    # 3️⃣ Teilwort erlaubt
                    elif user_input in correct_answer:
                        correct = True

                    # 4️⃣ Tippfehler-Toleranz
                    else:
                        similarity_full = difflib.SequenceMatcher(None, user_input, correct_answer).ratio()
                        similarity_no_article = difflib.SequenceMatcher(None, user_input,
                                                                        correct_without_article).ratio()

                        if similarity_full >= 0.8 or similarity_no_article >= 0.8:
                            correct = True

                    if correct:
                        await msg.add_reaction('<:Astra_accept:1141303821176422460>')
                        await cur.execute("DELETE FROM emojiquiz_lsg WHERE guildID = %s", (msg.guild.id,))

                        # Belohnung auszahlen
                        await self.economy.update_balance(msg.author.id, wallet_change=20)

                        import asyncio
                        await asyncio.sleep(2)

                        # Alle gespeicherten User-Nachrichten löschen
                        await cur.execute(
                            "SELECT messageID FROM emojiquiz_messages WHERE guildID = %s AND channelID = %s",
                            (msg.guild.id, msg.channel.id)
                        )
                        all_msg_ids = await cur.fetchall()

                        for (mid,) in all_msg_ids:
                            try:
                                m = await msg.channel.fetch_message(mid)
                                await m.delete()
                            except Exception:
                                pass

                        await cur.execute(
                            "DELETE FROM emojiquiz_messages WHERE guildID = %s AND channelID = %s",
                            (msg.guild.id, msg.channel.id)
                        )

                        # Alte Quiznachricht löschen
                        if quiz_message_id:
                            try:
                                old_msg = await msg.channel.fetch_message(int(quiz_message_id))
                                await old_msg.delete()
                            except Exception:
                                pass

                        # Neues Quiz posten
                        query = "SELECT question, answer, hint FROM emojiquiz_quizzez ORDER BY RAND() LIMIT 1;"
                        await cur.execute(query)
                        quiz_data = await cur.fetchone()

                        if quiz_data:
                            question, answer, hint = quiz_data

                            emojiquiz_embed = discord.Embed(
                                title="Emojiquiz",
                                description="Solltest du Probleme beim Lösen haben, kannst du die Buttons dieser Nachricht benutzen.",
                                colour=discord.Colour.blue()
                            )

                            emojiquiz_embed.add_field(name="<:Astra_support:1141303923752325210>  Gesuchter Begriff", value=question, inline=True)
                            emojiquiz_embed.add_field(name="<:Astra_wichtig:1141303951862534224>  Tipp", value=f"||{hint}||", inline=True)
                            emojiquiz_embed.set_footer(
                                text=f"Das letzte Quiz wurde von {msg.author.name} erraten!",
                                icon_url=msg.author.avatar.url
                            )

                            sent = await msg.channel.send(
                                embed=emojiquiz_embed,
                                view=buttons_emj(bot=self.bot, economy=self.economy)
                            )

                            await cur.execute(
                                "UPDATE emojiquiz SET messageID = %s WHERE guildID = %s",
                                (sent.id, msg.guild.id)
                            )

                            await cur.execute(
                                "INSERT INTO emojiquiz_lsg(guildID, lösung) VALUES (%s, %s)",
                                (msg.guild.id, answer)
                            )

                    else:
                        try:
                            await msg.add_reaction('<:Astra_x:1141303954555289600>')
                        except Exception:
                            pass

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(buttons_emj(bot=self.bot, economy=self.economy))

    @app_commands.command(name="emojiquiz", description="Emojiquiz in einem Kanal ein- oder ausschalten")
    @app_commands.describe(status="Legt fest, ob das Quiz eingeschaltet ('An') oder ausgeschaltet ('Aus') wird.", channel="Der Kanal, in dem das Quiz angezeigt werden soll (nur bei 'An').")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def emojiquiz(self, interaction: discord.Interaction, status: Literal['An', 'Aus'],
                        channel: discord.TextChannel):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if status == "An":
                    await cur.execute("SELECT channelID, messageID FROM emojiquiz WHERE guildID = (%s)",
                                      (interaction.guild.id,))
                    already_on = await cur.fetchone()
                    if already_on:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Das Emojiquizz ist bereits aktiviert.")
                    else:
                        query = "SELECT question, answer, hint FROM emojiquiz_quizzez ORDER BY RAND() LIMIT 1;"
                        await cur.execute(query)
                        quiz_data = await cur.fetchone()
                        if quiz_data:
                            question, answer, hint = quiz_data

                            emojiquiz_embed = discord.Embed(
                                title="Emojiquiz",
                                description="Solltest du Probleme beim Lösen haben, kannst du die Buttons dieser Nachricht benutzen.",
                                colour=discord.Colour.blue())
                            emojiquiz_embed.add_field(name="<:Astra_support:1141303923752325210>  Gesuchter Begriff", value=question, inline=True)
                            emojiquiz_embed.add_field(name="<:Astra_wichtig:1141303951862534224>  Tipp", value=f"||{hint}||", inline=True)
                            emojiquiz_embed.set_footer(
                                text=f"Das letzte Quiz wurde von {interaction.user.name} erraten!",
                                icon_url=interaction.user.avatar)

                            sent = await channel.send(embed=emojiquiz_embed,
                                                      view=buttons_emj(bot=self.bot, economy=self.economy))
                            await cur.execute(
                                "INSERT INTO emojiquiz(guildID, channelID, messageID) VALUES (%s, %s, %s)",
                                (interaction.guild.id, channel.id, sent.id))
                            await cur.execute(
                                "INSERT INTO emojiquiz_lsg(guildID, lösung) VALUES (%s, %s)",
                                (interaction.guild.id, answer))
                            await interaction.response.send_message(
                                "<:Astra_accept:1141303821176422460> Das Emojiquiz ist nun aktiviert!")

                if status == "Aus":
                    await cur.execute("SELECT channelID, messageID FROM emojiquiz WHERE guildID = (%s)",
                                      (interaction.guild.id,))
                    already_off = await cur.fetchone()
                    if not already_off:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Das Emojiquizz ist bereits deaktiviert.")
                    else:
                        channel_id, msg_id = already_off
                        # Versuche, die Quiznachricht zu löschen
                        try:
                            quiz_channel = self.bot.get_channel(channel_id)
                            quiz_msg = await quiz_channel.fetch_message(msg_id)
                            await quiz_msg.delete()
                        except Exception:
                            pass  # Ignoriere Fehler beim Löschen

                        await cur.execute(
                            "DELETE FROM emojiquiz WHERE guildID = (%s) AND channelID = (%s)",
                            (interaction.guild.id, channel.id))
                        await cur.execute(
                            "DELETE FROM emojiquiz_lsg WHERE guildID = %s",
                            (interaction.guild.id,))
                        await interaction.response.send_message(
                            "<:Astra_accept:1141303821176422460> Das Emojiquiz ist nun deaktiviert!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(emojiquiz(bot))
