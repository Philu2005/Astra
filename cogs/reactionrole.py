import discord
from discord.ext import commands
from discord import app_commands, ui, Interaction
from typing import List, Literal
import aiomysql
import re
from discord.ui import RoleSelect as NativeRoleSelect

class RoleConfigModal(ui.Modal, title="Rolle konfigurieren"):
    label_input = ui.TextInput(label="Anzeigename für die Rolle", required=True)
    emoji_input = ui.TextInput(label="Emoji (Standard oder benutzerdefiniert)", required=False)

    def __init__(self, role: discord.Role):
        super().__init__()
        self.role = role

    async def on_submit(self, interaction: Interaction):
        self.result = {
            "role_id": self.role.id,
            "label": self.label_input.value,
            "emoji": self.emoji_input.value or None
        }
        await interaction.response.defer()
        self.stop()

def is_valid_emoji(emoji: str):
    custom_emoji_pattern = re.compile(r'<a?:[a-zA-Z0-9_~]+:[0-9]+>')
    standard_emoji_pattern = re.compile(r'^[#-9©® -㌀ἀ0-ᾟF]+$')
    return custom_emoji_pattern.match(emoji) or standard_emoji_pattern.match(emoji)

class FinalEmbedModal(ui.Modal, title="Erstelle das endgültige Embed"):
    title_input = ui.TextInput(label="Embed Titel", max_length=256, required=True)
    desc_input = ui.TextInput(label="Embed Beschreibung", style=discord.TextStyle.paragraph, required=True)
    color_input = ui.TextInput(label="Farbe (Hex, optional)", required=False)
    thumbnail_input = ui.TextInput(label="Thumbnail URL (optional)", required=False)
    image_input = ui.TextInput(label="Image URL (optional)", required=False)

    async def on_submit(self, interaction: Interaction):
        self.embed_data = {
            "title": self.title_input.value,
            "description": self.desc_input.value,
            "color": int(self.color_input.value.lstrip('#'), 16) if self.color_input.value else 0x2F3136,
            "thumbnail": self.thumbnail_input.value,
            "image": self.image_input.value
        }
        await interaction.response.defer()
        self.stop()

class RoleSelectView(ui.View):
    def __init__(self, interaction: discord.Interaction, roles: List[discord.Role], style: str):
        super().__init__(timeout=None)
        self.interaction = interaction
        self.roles = roles
        self.selected = []
        self.role_data = []
        self.embed_message = None
        self.embed = discord.Embed(title="Reaktionsrollen Setup", description="Füge Rollen über das Select-Menü hinzu oder entferne sie durch erneute Auswahl.", color=discord.Color.blue())
        self.embed.set_footer(text="Reaction Roles Setup")
        self.style = style
        self.embed_data = None

        # ✨ Nutze natives RoleSelect-Menü
        self.select = NativeRoleSelect(placeholder="Wähle eine Rolle aus", min_values=1, max_values=1, custom_id="native_role_select")
        self.select.callback = self.select_callback
        self.add_item(self.select)

        self.add_item(SaveButton())
        self.add_item(CancelButton())

    async def select_callback(self, interaction: Interaction):
        role_id = int(interaction.data["values"][0])
        role = interaction.guild.get_role(role_id)

        existing = next((r for r in self.role_data if r["role_id"] == role_id), None)
        if existing:
            self.role_data.remove(existing)
            self.selected.remove(role_id)
        else:
            modal = RoleConfigModal(role)
            await interaction.response.send_modal(modal)
            await modal.wait()
            self.role_data.append(modal.result)
            self.selected.append(role_id)

        self.embed.clear_fields()
        for r in self.role_data:
            self.embed.add_field(name=r["label"], value=f"<@&{r['role_id']}>", inline=False)

        if self.embed_message is None:
            self.embed_message = await interaction.followup.send(embed=self.embed, view=self, ephemeral=True)
        else:
            await self.embed_message.edit(embed=self.embed, view=self)

class SaveButton(ui.Button):
    def __init__(self):
        super().__init__(label="Fertig", style=discord.ButtonStyle.green, emoji="<:Astra_accept:1141303821176422460>", custom_id="save_button")

    async def callback(self, interaction: Interaction):
        final_modal = FinalEmbedModal()
        await interaction.response.send_modal(final_modal)
        await final_modal.wait()
        self.view.embed_data = final_modal.embed_data
        await interaction.followup.send("<:Astra_accept:1141303821176422460> Embed-Konfiguration abgeschlossen.", ephemeral=True)
        self.view.stop()

class CancelButton(ui.Button):
    def __init__(self):
        super().__init__(label="Abbrechen", style=discord.ButtonStyle.danger, emoji="<:Astra_x:1141303954555289600>", custom_id="cancel_button")

    async def callback(self, interaction: Interaction):
        await interaction.response.send_message("<:Astra_x:1141303954555289600> Reaktionsrollen-Setup abgebrochen.", ephemeral=True)
        self.view.stop()

class ReactionRoleContainerView(discord.ui.LayoutView):

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        role_data: list,
        style: str
    ):
        super().__init__(timeout=None)

        self.bot = bot
        self.guild = guild
        self.role_data = role_data
        self.style = style.lower()

        self._build()

    # =========================================================
    # BUILD PANEL
    # =========================================================

    def _build(self):
        self.clear_items()

        main = discord.ui.Container(
            accent_color=discord.Colour.blue().value
        )

        # =====================================================
        # HEADER
        # =====================================================

        main.add_item(discord.ui.TextDisplay(
            "# 🎭 ReactionRole System\n"
            "Wähle deine gewünschten Rollen ganz bequem über die untenstehenden\n"
            "Buttons oder das Auswahlmenü aus.\n\n"
            "Du kannst Rollen jederzeit wieder entfernen."
        ))

        main.add_item(discord.ui.Separator())

        # =====================================================
        # INFO SECTION
        # =====================================================

        style_text = "Buttons" if self.style == "buttons" else "Auswahlliste"

        main.add_item(discord.ui.TextDisplay(
            f"## ⚙️ Auswahlmodus\n"
            f"**Aktueller Stil:** `{style_text}`\n\n"
            "<:Astra_punkt:1141303896745201696> Mehrfachauswahl möglich\n"
            "<:Astra_punkt:1141303896745201696> Rollen können wieder entfernt werden\n"
            "<:Astra_punkt:1141303896745201696> Änderungen sind sofort aktiv"
        ))

        main.add_item(discord.ui.Separator())

        # =====================================================
        # ROLE COMPONENTS
        # =====================================================

        if self.style in ["buttons", "button"]:

            for r in self.role_data:

                role = self.guild.get_role(r['role_id'])

                btn = discord.ui.Button(
                    label=r['label'],
                    emoji=r['emoji'],
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"rr_button_{r['role_id']}"
                )

                async def button_callback(interaction: discord.Interaction, rid=r['role_id']):
                    role = interaction.guild.get_role(rid)

                    if role in interaction.user.roles:
                        await interaction.user.remove_roles(role)
                        await interaction.response.send_message(
                            f"<:Astra_accept:1141303821176422460> Rolle **{role.name}** entfernt.",
                            ephemeral=True
                        )
                    else:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message(
                            f"<:Astra_accept:1141303821176422460> Rolle **{role.name}** vergeben.",
                            ephemeral=True
                        )

                btn.callback = button_callback
                main.add_item(discord.ui.ActionRow(btn))

        else:

            options = []

            for r in self.role_data:
                options.append(
                    discord.SelectOption(
                        label=r['label'],
                        value=str(r['role_id']),
                        emoji=r['emoji']
                    )
                )

            select = discord.ui.Select(
                placeholder="🎭 Wähle deine Rollen aus...",
                options=options,
                min_values=0,
                max_values=len(options),
                custom_id="rr_select_container"
            )

            async def select_callback(interaction: discord.Interaction):
                selected = [int(v) for v in select.values]
                added, removed = [], []

                user_roles = [r.id for r in interaction.user.roles]

                for option in options:
                    rid = int(option.value)
                    role = interaction.guild.get_role(rid)

                    if rid in selected and rid not in user_roles:
                        await interaction.user.add_roles(role)
                        added.append(role.name)

                    elif rid not in selected and rid in user_roles:
                        await interaction.user.remove_roles(role)
                        removed.append(role.name)

                msg = []

                if added:
                    msg.append(
                        f"<:Astra_accept:1141303821176422460> Rollen vergeben: {', '.join(added)}"
                    )

                if removed:
                    msg.append(
                        f"<:Astra_x:1141303954555289600> Rollen entfernt: {', '.join(removed)}"
                    )

                if msg:
                    await interaction.response.send_message(
                        "\n".join(msg),
                        ephemeral=True
                    )
                else:
                    await interaction.response.defer()

            select.callback = select_callback

            main.add_item(discord.ui.ActionRow(select))

        main.add_item(discord.ui.Separator())

        main.add_item(discord.ui.TextDisplay(
            "<:Astra_support:1141303923752325210> "
            "Wähle oder entferne deine Rollen jederzeit über dieses Panel."
        ))

        self.add_item(main)

class ReactionRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="reactionrole", description="Erstellt eine Reaction-Role-Nachricht.")
    @app_commands.describe(style="Art der Auswahl: 'buttons' (Buttons) oder 'select' (Auswahlliste).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def reactionrole(self, interaction: discord.Interaction, style: Literal["buttons", "select"]):
        roles = [role for role in interaction.guild.roles if role.name != "@everyone"]
        view = RoleSelectView(interaction, roles, style)
        await interaction.response.send_message("Wähle Rollen für deine Reaktionsrollen aus.", view=view, ephemeral=True)
        await view.wait()

        if not hasattr(view, 'embed_data'):
            return

        embed_data = view.embed_data
        embed = discord.Embed(title=embed_data['title'], description=embed_data['description'], color=embed_data['color'])
        if embed_data['thumbnail']:
            embed.set_thumbnail(url=embed_data['thumbnail'])
        if embed_data['image']:
            embed.set_image(url=embed_data['image'])

        role_data = view.role_data
        view_final = ReactionRoleContainerView(
            self.bot,
            interaction.guild,
            role_data,
            style
        )
        msg = await interaction.channel.send(embed=embed, view=view_final)
        self.bot.add_view(view_final, message_id=msg.id)

        async with interaction.client.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO reactionrole_messages 
                    (message_id, guild_id, channel_id, style, embed_title, embed_description, embed_color, embed_image, embed_thumbnail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    msg.id,
                    interaction.guild.id,
                    interaction.channel.id,
                    style,
                    embed_data['title'],
                    embed_data['description'],
                    f"{embed_data['color']:06x}",
                    embed_data['image'],
                    embed_data['thumbnail']
                ))

                for r in role_data:
                    await cursor.execute("""
                        INSERT INTO reactionrole_entries (message_id, role_id, label, emoji)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        msg.id,
                        r['role_id'],
                        r['label'],
                        r['emoji']
                    ))

    @commands.Cog.listener()
    async def on_ready(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT message_id, style FROM reactionrole_messages")
                for msg_id, style in await cursor.fetchall():
                    await cursor.execute("SELECT role_id, label, emoji FROM reactionrole_entries WHERE message_id = %s", (msg_id,))
                    role_data = [
                        {"role_id": rid, "label": label, "emoji": emoji}
                        for rid, label, emoji in await cursor.fetchall()
                    ]
                    view = await self.setup_persistent_view(role_data, style)
                    self.bot.add_view(view, message_id=msg_id)

async def setup(bot):
    await bot.add_cog(ReactionRole(bot))