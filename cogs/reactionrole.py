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

class ReactionRoleManageView(discord.ui.LayoutView):

    def __init__(self, interaction: discord.Interaction, panels: list[dict]):
        super().__init__(timeout=300)

        self.interaction = interaction
        self.panels = panels
        self.selected_panel = None

        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.interaction.user.id

    def _build(self):
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Color.orange().value
        )

        container.add_item(discord.ui.TextDisplay(
            "# 📋 ReactionRole Verwaltung\n"
            "Wähle ein Panel aus, um es zu verwalten."
        ))

        container.add_item(discord.ui.Separator())

        if not self.panels:
            container.add_item(discord.ui.TextDisplay(
                "❌ Es existieren keine ReactionRole Panels."
            ))
            self.add_item(container)
            return

        options = [
            discord.SelectOption(
                label=p["embed_title"][:100],
                description=f"Channel: {p['channel_id']} | Style: {p['style']}",
                value=str(p["message_id"])
            )
            for p in self.panels
        ]

        select = discord.ui.Select(
            placeholder="Panel auswählen...",
            options=options
        )

        async def select_callback(interaction: discord.Interaction):
            panel_id = int(select.values[0])
            self.selected_panel = next(
                (p for p in self.panels if p["message_id"] == panel_id),
                None
            )

            self._build()
            await interaction.response.edit_message(view=self)

        select.callback = select_callback
        container.add_item(discord.ui.ActionRow(select))

        if self.selected_panel:
            container.add_item(discord.ui.Separator())

            container.add_item(discord.ui.TextDisplay(
                f"## 📝 Panel Informationen\n"
                f"**Titel:** {self.selected_panel['embed_title']}\n"
                f"**Channel:** <#{self.selected_panel['channel_id']}>\n"
                f"**Style:** {self.selected_panel['style']}\n"
                f"**Message ID:** `{self.selected_panel['message_id']}`"
            ))

            delete_btn = discord.ui.Button(
                label="Panel löschen",
                style=discord.ButtonStyle.danger,
                emoji="🗑"
            )

            async def delete_callback(interaction: discord.Interaction):

                async with interaction.client.pool.acquire() as conn:
                    async with conn.cursor() as cursor:

                        await cursor.execute(
                            "DELETE FROM reactionrole_entries WHERE message_id = %s",
                            (self.selected_panel["message_id"],)
                        )

                        await cursor.execute(
                            "DELETE FROM reactionrole_messages WHERE message_id = %s",
                            (self.selected_panel["message_id"],)
                        )

                        await conn.commit()

                channel = interaction.guild.get_channel(self.selected_panel["channel_id"])
                if channel:
                    try:
                        msg = await channel.fetch_message(self.selected_panel["message_id"])
                        await msg.delete()
                    except:
                        pass

                await interaction.response.send_message(
                    "✅ Panel wurde gelöscht.",
                    ephemeral=True
                )

                self.panels = [
                    p for p in self.panels
                    if p["message_id"] != self.selected_panel["message_id"]
                ]
                self.selected_panel = None
                self._build()
                await interaction.edit_original_response(view=self)

            delete_btn.callback = delete_callback

            container.add_item(discord.ui.ActionRow(delete_btn))

        self.add_item(container)




class RoleSelectView(discord.ui.LayoutView):

    def __init__(self, interaction: discord.Interaction, roles: List[discord.Role], style: str):
        super().__init__(timeout=None)

        self.interaction = interaction
        self.roles = roles
        self.style = style
        self.role_data = []
        self.embed_data = None

        self._build()

    def _build(self):
        self.clear_items()

        main = discord.ui.Container(
            accent_color=discord.Colour.blurple().value
        )

        # ================= HEADER =================

        main.add_item(discord.ui.TextDisplay(
            "# 🎭 ReactionRole Setup\n"
            "Wähle hier die Rollen aus, die später im Panel auswählbar sein sollen.\n"
            "Klicke eine Rolle an, um sie hinzuzufügen oder wieder zu entfernen."
        ))

        main.add_item(discord.ui.Separator())

        # ================= ROLE SELECT =================

        main.add_item(discord.ui.TextDisplay("## Rollen hinzufügen"))

        role_select = discord.ui.RoleSelect(
            placeholder="🎭 Rolle auswählen",
            min_values=1,
            max_values=1
        )

        async def role_select_cb(interaction: discord.Interaction):

            selected_role = role_select.values[0]

            existing = next(
                (r for r in self.role_data if r["role_id"] == selected_role.id),
                None
            )

            if existing:
                self.role_data.remove(existing)
                await interaction.response.send_message(
                    f"<:Astra_x:1141303954555289600> Rolle **{selected_role.name}** entfernt.",
                    ephemeral=True
                )
            else:
                modal = RoleConfigModal(selected_role)
                await interaction.response.send_modal(modal)
                await modal.wait()

                if hasattr(modal, "result") and modal.result:
                    self.role_data.append(modal.result)

            # View neu bauen und aktualisieren
            self._build()
            await interaction.edit_original_response(view=self)

        role_select.callback = role_select_cb

        # ⚠️ WICHTIG: Select darf NICHT in Section accessory
        main.add_item(discord.ui.ActionRow(role_select))

        # ================= AKTUELLE ROLLEN =================

        if self.role_data:
            roles_text = "\n".join(
                f"<@&{r['role_id']}> → **{r['label']}**"
                for r in self.role_data
            )
        else:
            roles_text = "`Noch keine Rollen hinzugefügt.`"

        main.add_item(discord.ui.TextDisplay(
            f"### 📋 Aktuelle Konfiguration\n{roles_text}"
        ))

        main.add_item(discord.ui.Separator())

        # ================= BUTTONS =================

        finish_btn = discord.ui.Button(
            label="Fertig",
            style=discord.ButtonStyle.success,
            emoji="<:Astra_accept:1141303821176422460>"
        )

        cancel_btn = discord.ui.Button(
            label="Abbrechen",
            style=discord.ButtonStyle.danger,
            emoji="<:Astra_x:1141303954555289600>"
        )

        async def finish_cb(interaction: discord.Interaction):

            if not self.role_data:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Du musst mindestens eine Rolle hinzufügen.",
                    ephemeral=True
                )

            modal = FinalEmbedModal()
            await interaction.response.send_modal(modal)
            await modal.wait()

            if hasattr(modal, "embed_data") and modal.embed_data:
                self.embed_data = modal.embed_data
                self.stop()

        async def cancel_cb(interaction: discord.Interaction):
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Reaktionsrollen-Setup abgebrochen.",
                ephemeral=True
            )
            self.stop()

        finish_btn.callback = finish_cb
        cancel_btn.callback = cancel_cb

        main.add_item(discord.ui.ActionRow(finish_btn, cancel_btn))

        main.add_item(discord.ui.Separator())

        main.add_item(discord.ui.TextDisplay(
            f"<:Astra_support:1141303923752325210> "
            f"Setup gestartet von {self.interaction.user.mention}"
        ))

        self.add_item(main)

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


@app_commands.guild_only()
class ReactionRoleGroup(app_commands.Group):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__(
            name="reactionrole",
            description="Verwalte ReactionRole Panels"
        )

    @app_commands.command(
        name="erstellen",
        description="Erstelle ein ReactionRole Panel."
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def erstellen(
        self,
        interaction: discord.Interaction,
        style: Literal["buttons", "select"]
    ):

        roles = [
            role for role in interaction.guild.roles
            if role.name != "@everyone"
        ]

        view = RoleSelectView(interaction, roles, style)

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )

        await view.wait()

        if not view.embed_data:
            return

        embed_data = view.embed_data

        embed = discord.Embed(
            title=embed_data["title"],
            description=embed_data["description"],
            color=embed_data["color"]
        )

        if embed_data["thumbnail"]:
            embed.set_thumbnail(url=embed_data["thumbnail"])

        if embed_data["image"]:
            embed.set_image(url=embed_data["image"])

        role_data = view.role_data

        cog = self.bot.get_cog("ReactionRole")
        view_final = await cog.setup_persistent_view(role_data, style)

        msg = await interaction.channel.send(embed=embed, view=view_final)
        self.bot.add_view(view_final, message_id=msg.id)

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                await cursor.execute("""
                    INSERT INTO reactionrole_messages
                    (message_id, guild_id, channel_id, style)
                    VALUES (%s,%s,%s,%s)
                """, (
                    msg.id,
                    interaction.guild.id,
                    interaction.channel.id,
                    style
                ))

                for r in role_data:
                    await cursor.execute("""
                        INSERT INTO reactionrole_entries
                        (message_id, role_id, label, emoji)
                        VALUES (%s,%s,%s,%s)
                    """, (
                        msg.id,
                        r["role_id"],
                        r["label"],
                        r["emoji"]
                    ))

    @app_commands.command(
        name="anzeigen",
        description="Zeige alle ReactionRole Panels."
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def anzeigen(self, interaction: discord.Interaction):

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT * FROM reactionrole_messages WHERE guild_id = %s",
                    (interaction.guild.id,)
                )
                panels = await cursor.fetchall()

        if not panels:
            return await interaction.response.send_message(
                "Keine Panels vorhanden.",
                ephemeral=True
            )

        view = ReactionRoleManageView(interaction, panels)

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


class ReactionRole(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def setup_persistent_view(self, role_data, style) -> ui.View:
        view = ui.View(timeout=None)

        def make_button_callback(rid):
            async def callback(i: discord.Interaction):
                role = i.guild.get_role(rid)

                if not role:
                    return await i.response.send_message(
                        "Rolle existiert nicht mehr.",
                        ephemeral=True
                    )

                if role in i.user.roles:
                    await i.user.remove_roles(role)
                    await i.response.send_message(
                        f"Rolle **{role.name}** entfernt.",
                        ephemeral=True
                    )
                else:
                    await i.user.add_roles(role)
                    await i.response.send_message(
                        f"Rolle **{role.name}** vergeben.",
                        ephemeral=True
                    )
            return callback

        if style.lower() in ["buttons", "button"]:
            for r in role_data:
                btn = ui.Button(
                    label=r["label"],
                    emoji=r["emoji"],
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"role_button_{r['role_id']}"
                )
                btn.callback = make_button_callback(r["role_id"])
                view.add_item(btn)

        else:
            options = []

            for r in role_data:
                emoji = None

                if r["emoji"]:
                    if r["emoji"].startswith("<"):
                        match = re.match(r"<a?:([a-zA-Z0-9_~]+):(\d+)>", r["emoji"])
                        if match:
                            emoji = discord.PartialEmoji(
                                name=match.group(1),
                                id=int(match.group(2))
                            )
                    else:
                        emoji = r["emoji"]

                options.append(
                    discord.SelectOption(
                        label=r["label"],
                        value=str(r["role_id"]),
                        emoji=emoji
                    )
                )

            select = ui.Select(
                placeholder="Wähle deine Rolle aus...",
                options=options,
                custom_id="reactionrole_select",
                min_values=0,
                max_values=len(options)
            )

            async def select_callback(i: discord.Interaction):
                selected = [int(v) for v in select.values]
                user_roles = [r.id for r in i.user.roles]

                added, removed = [], []

                for option in options:
                    rid = int(option.value)
                    role = i.guild.get_role(rid)

                    if not role:
                        continue

                    if rid in selected and rid not in user_roles:
                        await i.user.add_roles(role)
                        added.append(role.name)

                    elif rid not in selected and rid in user_roles:
                        await i.user.remove_roles(role)
                        removed.append(role.name)

                msg = []

                if added:
                    msg.append(f"Rollen vergeben: {', '.join(added)}")

                if removed:
                    msg.append(f"Rollen entfernt: {', '.join(removed)}")

                if msg:
                    await i.response.send_message("\n".join(msg), ephemeral=True)
                else:
                    await i.response.defer()

            select.callback = select_callback
            view.add_item(select)

        return view

    @commands.Cog.listener()
    async def on_ready(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                await cursor.execute(
                    "SELECT message_id, style FROM reactionrole_messages"
                )

                rows = await cursor.fetchall()

                for msg_id, style in rows:

                    await cursor.execute(
                        "SELECT role_id, label, emoji "
                        "FROM reactionrole_entries "
                        "WHERE message_id = %s",
                        (msg_id,)
                    )

                    role_data = [
                        {"role_id": rid, "label": label, "emoji": emoji}
                        for rid, label, emoji in await cursor.fetchall()
                    ]

                    view = await self.setup_persistent_view(role_data, style)
                    self.bot.add_view(view, message_id=msg_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRole(bot))
    bot.tree.add_command(ReactionRoleGroup(bot))