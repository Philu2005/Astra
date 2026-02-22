import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# BOTROLE VIEW
# =========================================================

class BotRoleView(discord.ui.LayoutView):

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        invoker: discord.User,
        enabled: bool,
        role: discord.Role | None
    ):
        super().__init__(timeout=None)

        self.bot = bot
        self.guild = guild
        self.invoker = invoker
        self.enabled = bool(enabled)
        self.role = role

        self._build()

    # =========================================================
    # DATABASE SAVE (INSERT OR UPDATE)
    # =========================================================

    async def _save(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                await cur.execute(
                    "SELECT guildID FROM botrole WHERE guildID = %s",
                    (self.guild.id,)
                )
                exists = await cur.fetchone()

                if exists:
                    await cur.execute(
                        """
                        UPDATE botrole
                        SET roleID = %s,
                            enabled = %s
                        WHERE guildID = %s
                        """,
                        (
                            self.role.id if self.role else None,
                            int(self.enabled),
                            self.guild.id
                        )
                    )
                else:
                    await cur.execute(
                        """
                        INSERT INTO botrole (guildID, roleID, enabled)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            self.guild.id,
                            self.role.id if self.role else None,
                            int(self.enabled)
                        )
                    )

                await conn.commit()

    # =========================================================
    # BUILD
    # =========================================================

    def _build(self):
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Colour.blurple().value
        )

        status_text = (
            "<:Astra_accept:1141303821176422460> **Aktiviert**"
            if self.enabled
            else "<:Astra_x:1141303954555289600> **Deaktiviert**"
        )

        container.add_item(discord.ui.TextDisplay(
            "# 🤖 Botrole System\n"
            "Automatische Rollenvergabe für neue Bots\n\n"
            f"**Status:** {status_text}\n"
            f"**Aktuelle Rolle:** {self.role.mention if self.role else '`Nicht gesetzt`'}"
        ))

        container.add_item(discord.ui.Separator())

        container.add_item(discord.ui.TextDisplay(
            "### ℹ️ Erklärung\n"
            "<:Astra_punkt:1141303896745201696> Neue Bots erhalten automatisch diese Rolle\n"
            "<:Astra_punkt:1141303896745201696> Es kann nur eine Botrole pro Server existieren\n"
            "<:Astra_punkt:1141303896745201696> Meine Bot-Rolle muss über dieser Rolle stehen\n"
            "<:Astra_punkt:1141303896745201696> Änderungen werden sofort gespeichert"
        ))

        container.add_item(discord.ui.Separator())

        # =====================================================
        # TOGGLE
        # =====================================================

        toggle = discord.ui.Button(
            label="System aktivieren" if not self.enabled else "System deaktivieren",
            emoji="<:Astra_light_on:1141303864134467675>" if not self.enabled
                  else "<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.success if not self.enabled
                  else discord.ButtonStyle.danger
        )

        async def toggle_cb(interaction: discord.Interaction):

            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            self.enabled = not self.enabled
            await self._save()

            self._build()
            await interaction.response.edit_message(view=self)

        toggle.callback = toggle_cb
        container.add_item(discord.ui.ActionRow(toggle))

        # =====================================================
        # ROLE SELECT
        # =====================================================

        role_select = discord.ui.RoleSelect(
            placeholder="🎭 Botrolle auswählen oder ändern",
            disabled=not self.enabled
        )

        async def role_cb(interaction: discord.Interaction):

            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            selected = role_select.values[0]

            if selected >= self.guild.me.top_role:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Diese Rolle ist höher oder gleich meiner Rolle.\n"
                    "Ziehe meine Rolle darüber.",
                    ephemeral=True
                )

            if selected.is_default():
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Die @everyone Rolle ist nicht erlaubt.",
                    ephemeral=True
                )

            self.role = selected
            await self._save()

            self._build()
            await interaction.response.edit_message(view=self)

        role_select.callback = role_cb
        container.add_item(discord.ui.ActionRow(role_select))

        container.add_item(discord.ui.Separator())

        container.add_item(discord.ui.TextDisplay(
            f"<:Astra_support:1141303923752325210> Bedienung durch {self.invoker.mention}"
        ))

        self.add_item(container)


# =========================================================
# COG
# =========================================================

class botrole(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # =====================================================
    # BOT JOIN EVENT
    # =====================================================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):

        if not member.bot:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT roleID, enabled FROM botrole WHERE guildID = %s",
                    (member.guild.id,)
                )
                result = await cur.fetchone()

        if not result:
            return

        role_id, enabled = result

        if not enabled or not role_id:
            return

        role = member.guild.get_role(int(role_id))
        if not role:
            return

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            print("Botrole Fehler: Rolle zu hoch.")
        except Exception as e:
            print(f"Botrole Fehler: {e}")

    # =====================================================
    # SLASH COMMAND
    # =====================================================

    @app_commands.command(
        name="botrole",
        description="Verwalte die automatische Rolle für neue Bots."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def botrole(self, interaction: discord.Interaction):

        guild = interaction.guild
        if not guild:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT roleID, enabled FROM botrole WHERE guildID = %s",
                    (guild.id,)
                )
                result = await cur.fetchone()

        role = None
        enabled = False

        if result:
            role_id, enabled = result
            enabled = bool(enabled)

            if role_id:
                role = guild.get_role(int(role_id))
                if role is None:
                    enabled = False

        view = BotRoleView(
            bot=self.bot,
            guild=guild,
            invoker=interaction.user,
            enabled=enabled,
            role=role
        )

        await interaction.response.send_message(
            view=view,
            ephemeral=True
        )


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(botrole(bot))