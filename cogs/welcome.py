import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from PIL.Image import Resampling
import aiohttp
import io
import re


# TODO(@Philu priority:medium due:2026-05-15 category:Welcome-System issue:veraltet risk:medium): Welcome-System auf neuesten Stand bringen


WELCOME_BANNER_PATH = "cogs/assets/Welcomecards/Willkommens_banner_fullsize.jpg"
FONT_PATH = "cogs/fonts/Exo-Regular.ttf"


# ================== UTILS ==================


def strip_emojis(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U00002600-\U000026FF"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub("", text)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = current + (" " if current else "") + word
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


# ================== BANNER GENERATOR ==================

async def generate_banner(member: discord.Member, subtitle: str | None) -> io.BytesIO:
    base = Image.open(WELCOME_BANNER_PATH).convert("RGBA")
    draw = ImageDraw.Draw(base)

    async with aiohttp.ClientSession() as session:
        async with session.get(member.display_avatar.url) as resp:
            avatar_buffer: io.BytesIO = io.BytesIO(await resp.read())

    SCALE = 4
    FINAL_SIZE = 304
    big_size = FINAL_SIZE * SCALE

    avatar = Image.open(avatar_buffer).convert("RGBA").resize(
        (big_size, big_size),
        Resampling.LANCZOS
    )

    mask = Image.new("L", (big_size, big_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big_size, big_size), fill=255)
    avatar.putalpha(mask)

    avatar = avatar.resize((FINAL_SIZE, FINAL_SIZE), Resampling.LANCZOS)
    base.paste(avatar, (29, 31), avatar)

    font_title = ImageFont.truetype(FONT_PATH, 30)
    font_desc = ImageFont.truetype(FONT_PATH, 22)
    font_count = ImageFont.truetype(FONT_PATH, 30)

    guild_name = strip_emojis(member.guild.name)

    # 🔧 FIX: %name im Banner
    subtitle = strip_emojis(subtitle) if subtitle else ""
    subtitle = subtitle.replace("%name", member.display_name)

    DESC_X = 400
    DESC_Y = 135
    DESC_WIDTH = 588
    DESC_HEIGHT = 160
    LINE_HEIGHT = 26
    TITLE_MARGIN = 12

    title_text = f"Willkommen auf {guild_name}"
    title_width = draw.textlength(title_text, font=font_title)

    lines = wrap_text(draw, subtitle, font_desc, DESC_WIDTH)
    max_lines = (DESC_HEIGHT // LINE_HEIGHT) - 1
    lines = lines[:max_lines]

    total_height = LINE_HEIGHT + TITLE_MARGIN + len(lines) * LINE_HEIGHT
    start_y = DESC_Y + (DESC_HEIGHT - total_height) // 2

    draw.text(
        (DESC_X + (DESC_WIDTH - title_width) // 2, start_y),
        title_text,
        font=font_title,
        fill=(255, 255, 255)
    )

    for i, line in enumerate(lines):
        line_width = draw.textlength(line, font=font_desc)
        draw.text(
            (
                DESC_X + (DESC_WIDTH - line_width) // 2,
                start_y + LINE_HEIGHT + TITLE_MARGIN + i * LINE_HEIGHT
            ),
            line,
            font=font_desc,
            fill=(220, 220, 220)
        )

    count_text = f"#{member.guild.member_count}"
    count_width = draw.textlength(count_text, font=font_count)

    COUNT_X = 832 + ((158 - count_width) // 2)
    COUNT_Y = 63

    draw.text((COUNT_X, COUNT_Y), count_text, font=font_count, fill=(255, 255, 255))

    out = io.BytesIO()
    base.save(out, format="PNG")
    out.seek(0)
    return out


# ================== MODALS ==================

class EmbedModal(discord.ui.Modal, title="Set Embed Welcome Message"):

    def __init__(self, bot, channel):
        super().__init__()
        self.bot = bot
        self.channel = channel

    text = discord.ui.TextInput(
        label="Embed Text",
        style=discord.TextStyle.long,
        placeholder="%mention Willkommen %name auf %guild!",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO welcome (guildID, channelID, message, mode)
                    VALUES (%s,%s,%s,'embed')
                    ON DUPLICATE KEY UPDATE
                        channelID=VALUES(channelID),
                        message=VALUES(message),
                        mode='embed'
                    """,
                    (interaction.guild.id, self.channel.id, self.text.value)
                )
        await interaction.response.send_message("✅ Embed Welcome gesetzt.", ephemeral=True)


class BannerModal(discord.ui.Modal, title="Banner Welcome konfigurieren"):

    def __init__(self, bot, channel):
        super().__init__()
        self.bot = bot
        self.channel = channel

    subtitle = discord.ui.TextInput(
        label="Banner Text (%name verfügbar)",
        style=discord.TextStyle.short,
        placeholder="Schön, dass du da bist %name!",
        max_length=160,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        subtitle_text = self.subtitle.value.strip() if self.subtitle.value else None

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO welcome (guildID, channelID, message, mode)
                    VALUES (%s,%s,%s,'banner')
                    ON DUPLICATE KEY UPDATE
                        channelID=VALUES(channelID),
                        message=VALUES(message),
                        mode='banner'
                    """,
                    (interaction.guild.id, self.channel.id, subtitle_text)
                )
        await interaction.response.send_message("✅ Banner Welcome aktiviert.", ephemeral=True)


# ================== COG ==================

class welcome(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT channelID, message, mode FROM welcome WHERE guildID=%s",
                    (member.guild.id,)
                )
                data = await cursor.fetchone()

        if not data:
            return

        channel_id, message, mode = data
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return

        if mode == "banner":
            card = await generate_banner(member, message)

            file = discord.File(card, filename="welcome.png")
            embed = discord.Embed(color=discord.Color.blurple())
            embed.set_image(url="attachment://welcome.png")

            await channel.send(embed=embed, file=file)

        elif mode == "embed":
            text = (
                message
                .replace("%member", str(member))
                .replace("%name", member.display_name)
                .replace("%mention", member.mention)
                .replace("%guild", member.guild.name)
                .replace("%usercount", str(member.guild.member_count))
            )

            try:

                await channel.send(embed=discord.Embed(description=text, colour=discord.Colour.blue()))

            except discord.Forbidden:
                owner = member.guild.owner

                if owner:
                    try:
                        embed = discord.Embed(
                            title="⚠️ Problem im Willkommen-System",
                            description=(
                                f"In deinem Server **{member.guild.name}** konnte ich keine Willkommensnachricht senden.\n\n"
                                f"**Betroffener Channel:** <#{channel_id}>\n\n"
                                f"Mir fehlen dort die nötigen Berechtigungen."
                            ),
                            color=discord.Color.blue()
                        )

                        embed.add_field(
                            name="🔧 Benötigte Rechte",
                            value=(
                                "• Send Messages\n"
                                "• Embed Links\n"
                                "• Attach Files (für Banner)"
                            ),
                            inline=False
                        )

                        if member.guild.icon:
                            embed.set_thumbnail(url=member.guild.icon.url)

                        embed.set_footer(text="Bitte überprüfe die Channel- oder Rollenberechtigungen des Bots.")

                        await owner.send(embed=embed)
                    except discord.Forbidden:
                        pass

    @app_commands.command(name="testjoin", description="Simuliert einen Member-Join für das Welcome-System")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testjoin(self, interaction: discord.Interaction):
        member = interaction.user
        await self.on_member_join(member)
        await interaction.response.send_message("✅ Testjoin ausgeführt.", ephemeral=True)

    @app_commands.command(name="joinmsg", description="Konfiguriere die Willkommensnachricht (Banner oder Embed)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def joinmsg(
        self,
        interaction: discord.Interaction,
        argument: Literal["Einschalten", "Ausschalten", "Anzeigen"],
        channel: discord.TextChannel = None,
        mode: Literal["banner", "embed"] = "embed"
    ):
        if argument == "Einschalten":
            if not channel:
                await interaction.response.send_message("❌ Kanal fehlt.", ephemeral=True)
                return
            if mode == "embed":
                await interaction.response.send_modal(EmbedModal(self.bot, channel))
            else:
                await interaction.response.send_modal(BannerModal(self.bot, channel))

        elif argument == "Ausschalten":
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM welcome WHERE guildID=%s",
                        (interaction.guild.id,)
                    )
            await interaction.response.send_message("✅ Welcome deaktiviert.", ephemeral=True)

        elif argument == "Anzeigen":
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT channelID, message, mode FROM welcome WHERE guildID=%s",
                        (interaction.guild.id,)
                    )
                    data = await cursor.fetchone()

            if not data:
                await interaction.response.send_message("❌ Kein Welcome aktiv.", ephemeral=True)
                return

            ch = interaction.guild.get_channel(data[0])
            msg = data[1] or "—"

            await interaction.response.send_message(
                f"📢 Kanal: {ch.mention}\n🎨 Modus: **{data[2]}**\n📝 Text:\n```{msg}```",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(welcome(bot))