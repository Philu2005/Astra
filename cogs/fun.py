import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from PIL import Image, ImageOps, ImageDraw
from io import BytesIO
import pyfiglet
from typing import Optional
import io
import aiohttp
import urllib.parse
import qrcode
import os
import requests
import random
import asyncio
from utils.branding import get_current_colour


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


def check():
    print(1)

    def nsfw(interaction: discord.Interaction):
        print(2)
        return interaction.channel.is_nsfw()

    print(3)

    return app_commands.check(nsfw)


def make_qr(filename, msg):
    img = qrcode.make(msg)
    img.save(filename)


class fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -- wanted ---------------------------------------------------------
    @app_commands.command(name="wanted", description="Erstellt ein klassisches 'Wanted'-Plakat mit einem Profilbild.")
    @app_commands.guild_only()
    @app_commands.describe(
        member="Der Nutzer, dessen Avatar verwendet werden soll (leer lassen = du selbst)."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def wanted(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Erstellt ein 'Wanted'-Plakat mit dem Avatar eines Users und sendet es als Bild."""
        member = member or interaction.user
        wanted = Image.open("wanted.jpg")
        asset = member.avatar
        data = BytesIO(await asset.read())
        pfp = Image.open(data).resize((307, 307))
        wanted.paste(pfp, (165, 273))
        wanted.save("profile.jpg")

        embed = discord.Embed(
            description=f"**Nach {member} wird gefahndet!**",
            colour=get_current_colour()
        )
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar)
        file = discord.File("profile.jpg", filename="profile.jpg")
        embed.set_image(url="attachment://profile.jpg")
        await interaction.response.send_message(file=file, embed=embed)
        os.remove("profile.jpg")

    # -- pix ------------------------------------------------------------
    @app_commands.command(name="pix", description="Verpixelt das Profilbild eines Nutzers.")
    @app_commands.guild_only()
    @app_commands.describe(
        member="Der Nutzer, dessen Avatar verpixelt werden soll (leer lassen = du selbst)."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def pix(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        """Skaliert den Avatar stark herunter und wieder hoch – klassischer Pixel-Effekt."""
        member = member or interaction.user
        url = str(member.avatar).replace("gif", "png")
        img = Image.open(requests.get(url, stream=True).raw)
        old = img.size
        img = img.resize((16, 16)).resize(old)
        img.save('pix.png')

        embed = discord.Embed(
            description=f"**{member} wurde verpixelt!**",
            colour=get_current_colour()
        )
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar)
        file = discord.File("pix.png", filename="pix.png")
        embed.set_image(url="attachment://pix.png")
        await interaction.response.send_message(file=file, embed=embed)
        os.remove("pix.png")

    # -- wasted ---------------------------------------------------------
    @app_commands.command(name="wasted", description="Overlay im GTA-„Wasted“-Stil auf ein Profilbild legen.")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Der Nutzer, dessen Avatar genutzt wird (leer lassen = du selbst)."
    )
    async def wasted(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Verwendet SomeRandomAPI, um den GTA-„Wasted“-Effekt über den Avatar zu legen."""
        await interaction.response.defer()
        user = user or interaction.user
        avatar_url = user.display_avatar.replace(format="png", size=256).url
        encoded_url = urllib.parse.quote(avatar_url, safe='')
        api_url = f"https://some-random-api.com/canvas/wasted?avatar={encoded_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("❌ Fehler bei der API-Anfrage.", ephemeral=True)
                img_bytes = await resp.read()
                file = discord.File(io.BytesIO(img_bytes), filename="wasted.png")
                embed = discord.Embed(description="**Wasted!**", color=get_current_colour())
                embed.set_image(url="attachment://wasted.png")
                await interaction.followup.send(embed=embed, file=file)

    # -- gay ------------------------------------------------------------
    @app_commands.command(name="gay", description="Regenbogen-Overlay auf ein Profilbild legen (Pride-Effekt).")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Der Nutzer, dessen Avatar genutzt wird (leer lassen = du selbst)."
    )
    async def gay(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Pride-/Rainbow-Filter via SomeRandomAPI – schnell und simpel."""
        await interaction.response.defer()
        user = user or interaction.user
        avatar_url = user.display_avatar.replace(format="png", size=256).url
        encoded_url = urllib.parse.quote(avatar_url, safe='')
        api_url = f"https://some-random-api.com/canvas/gay?avatar={encoded_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("❌ Fehler bei der API-Anfrage.", ephemeral=True)
                img_bytes = await resp.read()
                file = discord.File(io.BytesIO(img_bytes), filename="gay.png")
                embed = discord.Embed(description="🏳️‍🌈 **Gay!**", color=get_current_colour())
                embed.set_image(url="attachment://gay.png")
                await interaction.followup.send(embed=embed, file=file)

    # -- triggered ------------------------------------------------------
    @app_commands.command(name="triggered", description="Animierter „Triggered“-Effekt (GIF) auf ein Profilbild.")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Der Nutzer, dessen Avatar genutzt wird (leer lassen = du selbst)."
    )
    async def triggered(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Erstellt ein animiertes GIF mit „Triggered“-Overlay (SomeRandomAPI)."""
        await interaction.response.defer()
        user = user or interaction.user
        avatar_url = user.display_avatar.replace(format="png", size=256).url
        encoded_url = urllib.parse.quote(avatar_url, safe='')
        api_url = f"https://some-random-api.com/canvas/triggered?avatar={encoded_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("❌ Fehler bei der API-Anfrage.", ephemeral=True)
                img_bytes = await resp.read()
                file = discord.File(io.BytesIO(img_bytes), filename="triggered.gif")
                embed = discord.Embed(description="**Triggered!**", color=get_current_colour())
                embed.set_image(url="attachment://triggered.gif")
                await interaction.followup.send(embed=embed, file=file)

    # -- color ----------------------------------------------------------
    @app_commands.command(name="color", description="Zeigt eine Farbe als Bild (per Hex-Code).")
    @app_commands.guild_only()
    @app_commands.describe(
        hex="Hex-Code der Farbe, z. B. ff0055 oder #ff0055."
    )
    async def color(self, interaction: discord.Interaction, hex: str):
        """Rendert eine Farbvorschau über SomeRandomAPI – perfekt für Design & Rollenfarben."""
        hex_color = hex.lstrip("#")
        if len(hex_color) not in (3, 6):
            return await interaction.response.send_message(
                "Bitte einen gültigen Hex-Code (z. B. ff0055) angeben.", ephemeral=True
            )

        api_url = f"https://api.some-random-api.com/canvas/colorviewer?hex={hex_color}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return await interaction.response.send_message(
                        f"❌ Fehler bei der API-Anfrage ({resp.status}):\n{err}", ephemeral=True
                    )
                img_bytes = await resp.read()
                buf = io.BytesIO(img_bytes)
                file = discord.File(buf, filename="color.png")
                embed = discord.Embed(
                    title=f"Hier ist die Farbe #{hex_color}",
                    color=int(hex_color, 16) if len(hex_color) == 6 else None
                )
                embed.set_image(url="attachment://color.png")
                await interaction.response.send_message(embed=embed, file=file)

    # -- meme -----------------------------------------------------------
    @app_commands.command(name="meme", description="Zufälliges Meme aus beliebten Subreddits anzeigen.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def meme(self, interaction: discord.Interaction):
        """Holt ein frisches Meme von meme-api.com (Titel, Bild & Subreddit-Infos)."""
        await interaction.response.defer()
        memesubs = [
            "memes", "dankmemes", "wholesomememes", "meme", "me_irl",
            "comedyheaven", "2meirl4meirl", "Animemes", "ProgrammerHumor"
        ]
        chosen_sub = random.choice(memesubs)
        api_url = f"https://meme-api.com/gimme/{chosen_sub}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Fehler beim Abrufen des Memes.", ephemeral=True)
                data = await resp.json()
                embed = discord.Embed(
                    title=data.get("title", "Meme"),
                    url=data.get("postLink", ""),
                    color=discord.Color.blue()
                )
                embed.set_image(url=data.get("url", ""))
                embed.set_footer(
                    text=f"👍 {data.get('ups', 0)} | 💬 {data.get('num_comments', 0)} | von r/{data.get('subreddit', chosen_sub)}"
                )
                await interaction.followup.send(embed=embed)

    # -- qrcode ---------------------------------------------------------
    @app_commands.command(name="qrcode", description="Erstellt einen QR-Code für einen beliebigen Link.")
    @app_commands.guild_only()
    @app_commands.describe(
        link="Die URL/Text, die im QR-Code codiert werden soll."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def qrcode(self, interaction: discord.Interaction, link: str):
        """Generiert einen PNG-QR-Code aus deinem Link/Text und sendet ihn als Bild."""
        if link:
            make_qr("qrcode.png", link)
            embed = discord.Embed(
                description=f"**QR-Code für:** `{link}`",
                colour=get_current_colour()
            )
            embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar)
            file = discord.File("qrcode.png", filename="qrcode.png")
            embed.set_image(url="attachment://qrcode.png")
            await interaction.response.send_message(file=file, embed=embed)
            os.remove('qrcode.png')

    # -- lostrate -------------------------------------------------------
    @app_commands.command(name="lostrate", description="Schätzt spaßeshalber, wie „lost“ jemand ist (1–100%).")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Der Nutzer, der bewertet werden soll (leer lassen = du selbst)."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def lostrate(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Zufälliger Fun-Wert – reines Entertainment, nicht ernst nehmen!"""
        user = user or interaction.user
        x = random.randint(1, 100)
        embed = discord.Embed(colour=get_current_colour(), description=f"{user.mention} ist zu **{x}%** lost.")
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    # -- iq -------------------------------------------------------------
    @app_commands.command(name="iq", description="Generiert einen (nicht ernst gemeinten) IQ-Wert.")
    @app_commands.guild_only()
    @app_commands.describe(
        user="Der Nutzer, dessen „IQ“ geschätzt werden soll (leer lassen = du selbst)."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def iq(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Fun-Command: Zufallswert mit frechem Kommentar."""
        user = user or interaction.user
        x = random.randint(14, 230)
        if x < 40:
            iq = "ein ziemlicher **Chaot**."
        elif x < 80:
            iq = "eher **unterdurchschnittlich**."
        elif x < 150:
            iq = "**durchschnittlich** unterwegs."
        elif x < 200:
            iq = "**ziemlich smart** …"
        else:
            iq = "ein **SUPERGEHIRN**!"
        embed = discord.Embed(colour=get_current_colour(), description=f"Mit **{x} IQ** ist {user.mention} {iq}")
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    # -- ask ------------------------------------------------------------
    @app_commands.command(name="ask", description="Stell eine Frage – die Antwort kommt als GIF-Reaktion zurück.")
    @app_commands.guild_only()
    @app_commands.describe(
        frage="Deine Frage (z. B. „Magst du Pizza?“)."
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def ask(self, interaction: discord.Interaction, frage: str):
        """Antwortet mit einem zufälligen Ja/Nein/Maybe-GIF – perfekter Spaß für den Chat."""
        all_gifs = [
            'https://tenor.com/view/shrek-of-course-sarcasm-sarcastic-really-gif-14499396',
            'https://tenor.com/view/timon-lion-king-nope-no-shake-gif-3834543',
            'https://tenor.com/view/yes-nod-old-spice-oh-yes-commercial-gif-15384634',
            'https://tenor.com/view/agt-americas-got-talent-stop-buzzer-no-gif-4434972',
            'https://tenor.com/view/yes-melb-agt-americas-got-talent-agtgifs-gif-4519427',
            'https://tenor.com/view/egal-singing-ocean-sea-boat-ride-gif-16080257',
            'https://tenor.com/view/thats-a-no-elmo-shaking-shaking-head-nope-gif-7663315',
            'https://tenor.com/view/definitiv-nein-n%C3%B6-tv-total-raab-gif-11127197',
            'https://tenor.com/view/shannon-sharpe-shay-nope-nah-nuhuh-gif-12298561',
            'https://tenor.com/view/ja-jack-nicholson-fryslan-friesland-omrop-gif-12148366',
            'https://tenor.com/view/ok-okay-awkward-smile-gif-5307535',
            'https://tenor.com/view/elmo-shrug-gif-5094560',
            'https://tenor.com/view/horrible-crying-noooo-no-gif-11951898',
            'https://tenor.com/view/maaaayyybe-fallon-maybe-gif-5280420',
            'https://tenor.com/view/idk-i-dont-know-sebastian-stan-lol-wtf-gif-5364867',
            'https://tenor.com/view/yes-no-maybe-owl-funny-gif-13722109',
            'https://tenor.com/view/yes-minions-movie-minions-gi-fs-minions-gif-5026357',
            'https://tenor.com/view/steve-carell-no-please-no-gif-5026106',
            'https://tenor.com/view/obama-wtf-why-president-wut-gif-12221156',
            'https://tenor.com/view/trump-donald-trump-dance-thinking-idk-gif-5753267',
            'https://tenor.com/view/inauguration-cnn2017-donald-trump-finger-wag-no-absolutely-not-gif-12953442',
            'https://tenor.com/view/angela-merkel-keine-ahnung-no-clue-kanzlerin-deutschland-gif-11189427',
            'https://tenor.com/view/merkel-n%C3%B6-n%C3%B6merkel-merkel-meme-gif-gif-16050778',
            'https://tenor.com/view/angela-merkel-schmunzel-nicken-zufrieden-politik-gif-11862007'
        ]
        await interaction.response.send_message(f"**{frage}**\n\n{random.choice(all_gifs)}")

    # -- love -----------------------------------------------------------
    @app_commands.command(name="love", description="Wie gut passt ihr? Zeigt eine zufällige „Love-Rate“ für zwei Nutzer.")
    @app_commands.guild_only()
    @app_commands.describe(
        user1="Person A",
        user2="Person B"
    )
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def love(self, interaction: discord.Interaction, user1: discord.Member, user2: discord.Member):
        """Zweistufige Anzeige mit kurzer „Berechnung“ und anschließendem Ergebnis."""
        love_per = random.randint(1, 100)

        embed = discord.Embed(
            color=get_current_colour(),
            description=f"Sieh an, wie sehr {user1.mention} und {user2.mention} sich lieben … <3"
        )
        embed.add_field(name="❤️ Loverator", value="💌 Ich kalkuliere eure Liebe …")
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(3)

        embed2 = discord.Embed(
            color=get_current_colour(),
            description=f"Sieh an, wie sehr {user1.mention} und {user2.mention} sich lieben … <3"
        )
        embed2.add_field(name="❤️ Loverator", value=f"{user1.mention} und {user2.mention} lieben sich zu **{love_per}%**.")
        embed2.set_author(name=interaction.user, icon_url=interaction.user.avatar)

        msg = await interaction.original_response()
        await msg.edit(embed=embed2)

    # -- los ------------------------------------------------------------
    @app_commands.command(name="los", description="Ziehe ein Rubbellos – decke Felder auf und hoffe auf 🔵-Kombos.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def los(self, interaction: discord.Interaction):
        """Kleines Glückspiel-Minigame mit verdeckten Feldern."""
        choices = [["||⚪||", "||🔵||", "||⚪||", "||⚪||"] for _ in range(9)]
        grid = [random.choice(row) for row in choices]
        embed = discord.Embed(
            colour=get_current_colour(),
            title="Rubbellos",
            description=f"{grid[0]} {grid[1]} {grid[2]}\n{grid[3]} {grid[4]} {grid[5]}\n{grid[6]} {grid[7]} {grid[8]}\n"
        )
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        embed.set_footer(text="3x 🔵 in Reihe (vertikal/ horizontal/ diagonal) = Glück gehabt!")
        await interaction.response.send_message(embed=embed)

    # -- games ----------------------------------------------------------
    @app_commands.command(name="games", description="Zeigt, welche Spiele Mitglieder gerade spielen.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def games(self, interaction: discord.Interaction):
        """Listet laufende Discord-Game-Aktivitäten der Servermitglieder auf."""
        msg = ':chart: Aktuelle Spiele:\n```js\n'
        for member in interaction.guild.members:
            for activity in member.activities:
                if isinstance(activity, discord.Game):
                    msg += f'{activity}\n'
                elif isinstance(activity, discord.Activity):
                    msg += f'{activity.name}\n'
        msg += '```'
        await interaction.response.send_message(msg)

    # -- password -------------------------------------------------------
    @app_commands.command(name="password", description="Generiert ein zufälliges, starkes Passwort und sendet es per DM.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def password(self, interaction: discord.Interaction):
        """Erstellt ein 22-stelliges Passwort (Buchstaben & Zahlen) und schickt es dir privat."""
        user = interaction.user
        letters = list("aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ")
        choices = [
            f"{random.choice(letters)}", f"{random.randint(1, 9)}",
            f"{random.choice(letters)}", f"{random.randint(1, 9)}",
            f"{random.choice(letters)}", f"{random.randint(1, 9)}",
            f"{random.choice(letters)}", f"{random.randint(1, 9)}", f"{random.choice(letters)}"
        ]
        pwd = "".join(random.choice(choices) for _ in range(22))
        result = f"||{pwd}||"

        embed = discord.Embed(colour=get_current_colour(), title="🔐 Passwort",
                              description="**Gib dein Passwort niemals weiter.**")
        embed.set_author(name=user, icon_url=user.avatar)
        embed.add_field(name="Generiertes Passwort:", value=result)
        try:
            await user.send(embed=embed)
            await interaction.response.send_message(f"{user.mention}, ich habe dir das Passwort per DM gesendet.")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Ich konnte dir keine DM schicken. Bitte erlaube Direktnachrichten.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(fun(bot))
