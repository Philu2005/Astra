import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# AUTOROLE VIEW (BOT + MEMBER)
# =========================================================

class AutoroleView(discord.ui.LayoutView):

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        invoker: discord.User,
        bot_enabled: bool,
        bot_role: discord.Role | None,
        join_enabled: bool,
        join_role: discord.Role | None
    ):
        super().__init__(timeout=None)

        self.bot = bot
        self.guild = guild
        self.invoker = invoker

        self.bot_enabled = bool(bot_enabled)
        self.bot_role = bot_role

        self.join_enabled = bool(join_enabled)
        self.join_role = join_role

        self._build()

    # =========================================================
    # DATABASE SAVE
    # =========================================================

    async def _save(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                await cur.execute(
                    "SELECT guildID FROM autorole WHERE guildID = %s",
                    (self.guild.id,)
                )
                exists = await cur.fetchone()

                if exists:
                    await cur.execute(
                        """
                        UPDATE autorole
                        SET botRoleID = %s,
                            botEnabled = %s,
                            joinRoleID = %s,
                            joinEnabled = %s
                        WHERE guildID = %s
                        """,
                        (
                            self.bot_role.id if self.bot_role else None,
                            int(self.bot_enabled),
                            self.join_role.id if self.join_role else None,
                            int(self.join_enabled),
                            self.guild.id
                        )
                    )
                else:
                    await cur.execute(
                        """
                        INSERT INTO autorole
                        (guildID, botRoleID, botEnabled, joinRoleID, joinEnabled)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            self.guild.id,
                            self.bot_role.id if self.bot_role else None,
                            int(self.bot_enabled),
                            self.join_role.id if self.join_role else None,
                            int(self.join_enabled)
                        )
                    )

                await conn.commit()

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
            "# ⚙️ Autorole\n"
            "Das Autorole-System ermöglicht dir eine automatische Rollenvergabe,\n"
            "sobald neue Mitglieder oder Bots deinem Server beitreten."
        ))

        main.add_item(discord.ui.Separator())

        # =====================================================
        # JOINROLE SECTION
        # =====================================================

        join_status = (
            "<:Astra_accept:1141303821176422460> Aktiviert"
            if self.join_enabled
            else "<:Astra_x:1141303954555289600> Deaktiviert"
        )

        toggle_join = discord.ui.Button(
            label="Aktivieren" if not self.join_enabled else "Deaktivieren",
            emoji="<:Astra_light_on:1141303864134467675>" if not self.join_enabled
            else "<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.success if not self.join_enabled
            else discord.ButtonStyle.danger
        )

        async def toggle_join_cb(interaction: discord.Interaction):
            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            self.join_enabled = not self.join_enabled
            await self._save()
            self._build()
            await interaction.response.edit_message(view=self)

        toggle_join.callback = toggle_join_cb

        # SECTION (Text links, Button rechts)
        main.add_item(discord.ui.Section(
            discord.ui.TextDisplay("## Joinrole System"),
            accessory=toggle_join
        ))

        # Erklärung
        main.add_item(discord.ui.TextDisplay(
            "Vergibt automatisch eine festgelegte Rolle an neue Mitglieder,\n"
            "sobald sie dem Server beitreten.\n\n"
            "**Ideal für:**\n"
            "<:Astra_punkt:1141303896745201696> Standard-Mitgliedsrollen\n"
            "<:Astra_punkt:1141303896745201696> Verifizierungsprozesse\n"
            "<:Astra_punkt:1141303896745201696> Automatische Grundrechte\n\n"
            "<:Astra_light_on:1141303864134467675> Meine Bot-Rolle muss über der gewählten Rolle stehen!"
        ))

        # Status + Rolle
        main.add_item(discord.ui.TextDisplay(
            f"**Status:** {join_status}\n"
            f"**Aktuelle Rolle:** {self.join_role.mention if self.join_role else '`Nicht gesetzt`'}"
        ))

        role_join = discord.ui.RoleSelect(
            placeholder="🎭 Joinrolle auswählen oder ändern",
            disabled=not self.join_enabled
        )

        async def role_join_cb(interaction: discord.Interaction):
            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            selected = role_join.values[0]

            if selected >= self.guild.me.top_role:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Diese Rolle ist höher oder gleich meiner Rolle.",
                    ephemeral=True
                )

            if selected.is_default():
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Die @everyone Rolle ist nicht erlaubt.",
                    ephemeral=True
                )

            self.join_role = selected
            await self._save()
            self._build()
            await interaction.response.edit_message(view=self)

        role_join.callback = role_join_cb

        main.add_item(discord.ui.ActionRow(role_join))

        main.add_item(discord.ui.Separator())

        # =====================================================
        # BOTROLE SECTION
        # =====================================================

        bot_status = (
            "<:Astra_accept:1141303821176422460> Aktiviert"
            if self.bot_enabled
            else "<:Astra_x:1141303954555289600> Deaktiviert"
        )

        toggle_bot = discord.ui.Button(
            label="Aktivieren" if not self.bot_enabled else "Deaktivieren",
            emoji="<:Astra_light_on:1141303864134467675>" if not self.bot_enabled
            else "<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.success if not self.bot_enabled
            else discord.ButtonStyle.danger
        )

        async def toggle_bot_cb(interaction: discord.Interaction):
            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            self.bot_enabled = not self.bot_enabled
            await self._save()
            self._build()
            await interaction.response.edit_message(view=self)

        toggle_bot.callback = toggle_bot_cb

        main.add_item(discord.ui.Section(
            discord.ui.TextDisplay("## Botrole System"),
            accessory=toggle_bot
        ))

        main.add_item(discord.ui.TextDisplay(
            "Weist neu hinzugefügten Bots automatisch eine definierte Rolle zu,\n"
            "sobald sie deinem Server beitreten.\n\n"
            "**Perfekt geeignet für:**\n"
            "<:Astra_punkt:1141303896745201696> Bot-Kategorien\n"
            "<:Astra_punkt:1141303896745201696> Rechteverwaltung für Bots\n"
            "<:Astra_punkt:1141303896745201696> Klare optische Trennung von Bots & Mitgliedern\n\n"
            "<:Astra_light_on:1141303864134467675> Meine Bot-Rolle muss über der gewählten Rolle stehen!"
        ))

        main.add_item(discord.ui.TextDisplay(
            f"**Status:** {bot_status}\n"
            f"**Aktuelle Rolle:** {self.bot_role.mention if self.bot_role else '`Nicht gesetzt`'}"
        ))

        role_bot = discord.ui.RoleSelect(
            placeholder="🎭 Botrolle auswählen oder ändern",
            disabled=not self.bot_enabled
        )

        async def role_bot_cb(interaction: discord.Interaction):
            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            selected = role_bot.values[0]

            if selected >= self.guild.me.top_role:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Diese Rolle ist höher oder gleich meiner Rolle.",
                    ephemeral=True
                )

            if selected.is_default():
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Die @everyone Rolle ist nicht erlaubt.",
                    ephemeral=True
                )

            self.bot_role = selected
            await self._save()
            self._build()
            await interaction.response.edit_message(view=self)

        role_bot.callback = role_bot_cb

        main.add_item(discord.ui.ActionRow(role_bot))

        main.add_item(discord.ui.Separator())

        main.add_item(discord.ui.TextDisplay(
            f"<:Astra_support:1141303923752325210> Bedienung durch {self.invoker.mention}"
        ))

        self.add_item(main)


# =========================================================
# COG
# =========================================================

class autorole(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ==========================
    # BOT JOIN
    # ==========================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT botRoleID, botEnabled, joinRoleID, joinEnabled FROM autorole WHERE guildID = %s",
                    (member.guild.id,)
                )
                result = await cur.fetchone()

        if not result:
            return

        bot_role_id, bot_enabled, join_role_id, join_enabled = result

        try:
            if member.bot and bot_enabled and bot_role_id:
                role = member.guild.get_role(int(bot_role_id))
                if role:
                    await member.add_roles(role)

            if not member.bot and join_enabled and join_role_id:
                role = member.guild.get_role(int(join_role_id))
                if role:
                    await member.add_roles(role)

        except discord.Forbidden:
            print("Autorole Fehler: Rolle zu hoch.")
        except Exception as e:
            print(f"Autorole Fehler: {e}")

    # ==========================
    # SLASH COMMAND
    # ==========================

    @app_commands.command(
        name="autorole",
        description="Verwalte die automatische Rolle für neue Bots und Mitglieder."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorole(self, interaction: discord.Interaction):

        guild = interaction.guild
        if not guild:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT botRoleID, botEnabled, joinRoleID, joinEnabled FROM autorole WHERE guildID = %s",
                    (guild.id,)
                )
                result = await cur.fetchone()

        bot_role = None
        bot_enabled = False
        join_role = None
        join_enabled = False

        if result:
            bot_role_id, bot_enabled, join_role_id, join_enabled = result
            bot_enabled = bool(bot_enabled)
            join_enabled = bool(join_enabled)

            if bot_role_id:
                bot_role = guild.get_role(int(bot_role_id))
            if join_role_id:
                join_role = guild.get_role(int(join_role_id))

        view = AutoroleView(
            bot=self.bot,
            guild=guild,
            invoker=interaction.user,
            bot_enabled=bot_enabled,
            bot_role=bot_role,
            join_enabled=join_enabled,
            join_role=join_role
        )

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(autorole(bot))