import discord
from discord.ext import commands
from discord import app_commands
from typing import Literal
from utils.branding import get_current_colour


# =========================
# MODAL: TAG ERSTELLEN
# =========================
class TagCreateModal(discord.ui.Modal, title="Tag erstellen"):
    tagname = discord.ui.TextInput(
        label="Tag-Name",
        placeholder="z. B. astra, hilfe",
        max_length=100
    )

    tagoutput = discord.ui.TextInput(
        label="Tag-Inhalt",
        placeholder="Markdown, Emojis & Zeilenumbrüche erlaubt",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO tags (guildID, tagname, tagoutput) VALUES (%s, %s, %s)",
                    (interaction.guild.id, self.tagname.value, self.tagoutput.value)
                )

        embed = discord.Embed(
            title="✅ Tag erstellt",
            colour=get_current_colour(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Name", value=f"a!{self.tagname.value}", inline=False)
        embed.add_field(name="Inhalt", value=self.tagoutput.value[:1024], inline=False)
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================
# VIEW: TAG PAGINATION
# =========================
class TagPaginationView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, tags: list[tuple[str, str]]):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.tags = tags
        self.index = 0

    def create_embed(self) -> discord.Embed:
        tagname, tagoutput = self.tags[self.index]
        embed = discord.Embed(
            title=f"🏷️ a!{tagname}",
            description=tagoutput,
            colour=get_current_colour(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(
            text=f"Tag {self.index + 1} von {len(self.tags)}"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "❌ Diese Buttons sind nicht für dich.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⬅️ Zurück", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.tags)
        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    @discord.ui.button(label="➡️ Weiter", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.tags)
        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# =========================
# TAGS COG
# =========================
class tags(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # TAG AUFRUF PER MESSAGE
    # =========================
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return

        if not msg.content.startswith("a!"):
            return

        tagname = msg.content[2:]

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT tagoutput FROM tags WHERE guildID = %s AND tagname = %s",
                    (msg.guild.id, tagname)
                )
                result = await cursor.fetchone()

        if not result:
            return

        embed = discord.Embed(
            title=f"__{tagname.upper()}__",
            description=result[0],
            colour=get_current_colour(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=msg.author, icon_url=msg.author.avatar)
        embed.set_thumbnail(url=msg.guild.icon)

        await msg.channel.send(embed=embed)

    # =========================
    # SLASH COMMAND: /tags
    # =========================
    @app_commands.command(
        name="tags",
        description="Erstelle eigene Befehle (Tags) für diesen Server."
    )
    @app_commands.describe(
        modus="Hinzufügen, Entfernen oder Anzeigen.",
        name="Name des Tags (nur bei Entfernen nötig)."
    )
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_messages=True)
    async def tags(
        self,
        interaction: discord.Interaction,
        modus: Literal["Hinzufügen", "Entfernen", "Anzeigen"],
        name: str = None
    ):
        # =========================
        # TAG HINZUFÜGEN → MODAL
        # =========================
        if modus == "Hinzufügen":
            await interaction.response.send_modal(TagCreateModal(self.bot))
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # =========================
                # TAG ENTFERNEN
                # =========================
                if modus == "Entfernen":
                    if not name:
                        await interaction.response.send_message(
                            "❌ Bitte gib einen Tagnamen an!",
                            ephemeral=True
                        )
                        return

                    await cursor.execute(
                        "SELECT tagname FROM tags WHERE guildID = %s AND tagname = %s",
                        (interaction.guild.id, name)
                    )
                    result = await cursor.fetchone()

                    if not result:
                        await interaction.response.send_message(
                            f"❌ Kein Tag mit dem Namen `{name}` gefunden.",
                            ephemeral=True
                        )
                        return

                    await cursor.execute(
                        "DELETE FROM tags WHERE guildID = %s AND tagname = %s",
                        (interaction.guild.id, name)
                    )

                    await interaction.response.send_message(
                        f"🗑️ Tag `{name}` wurde entfernt.",
                        ephemeral=True
                    )

                # =========================
                # TAGS ANZEIGEN (BUTTONS)
                # =========================
                if modus == "Anzeigen":
                    await cursor.execute(
                        "SELECT tagname, tagoutput FROM tags WHERE guildID = %s",
                        (interaction.guild.id,)
                    )
                    result = await cursor.fetchall()

                    if not result:
                        await interaction.response.send_message(
                            "ℹ️ Es existieren noch keine Tags auf diesem Server.",
                            ephemeral=True
                        )
                        return

                    view = TagPaginationView(interaction, result)
                    await interaction.response.send_message(
                        embed=view.create_embed(),
                        view=view
                    )


# =========================
# SETUP
# =========================
async def setup(bot: commands.Bot):
    await bot.add_cog(tags(bot))
