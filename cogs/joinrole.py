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

class JoinRoleView(discord.ui.LayoutView):

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

                # Prüfen ob Datensatz existiert
                await cur.execute(
                    "SELECT guildID FROM joinrole WHERE guildID = %s",
                    (self.guild.id,)
                )
                exists = await cur.fetchone()

                if exists:
                    # UPDATE
                    await cur.execute(
                        """
                        UPDATE joinrole
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
                    # INSERT
                    await cur.execute(
                        """
                        INSERT INTO joinrole (guildID, roleID, enabled)
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

        # =====================================================
        # HEADER
        # =====================================================

        status_text = (
            "<:Astra_accept:1141303821176422460> **Aktiviert**"
            if self.enabled
            else "<:Astra_x:1141303954555289600> **Deaktiviert**"
        )

        container.add_item(discord.ui.TextDisplay(
            "# 👋 Joinrole System\n"
            "Automatische Rollenvergabe für neue Mitglieder\n\n"
            f"**Status:** {status_text}\n"
            f"**Aktuelle Rolle:** {self.role.mention if self.role else '`Nicht gesetzt`'}"
        ))

        container.add_item(discord.ui.Separator())

        # =====================================================
        # ERKLÄRUNG
        # =====================================================

        container.add_item(discord.ui.TextDisplay(
            "### ℹ️ Erklärung\n"
            f"<:Astra_punkt:1141303896745201696> Neue Mitglieder erhalten automatisch die gewählte Rolle\n"
            f"<:Astra_punkt:1141303896745201696> Es kann nur eine Joinrolle pro Server existieren\n"
            f"<:Astra_punkt:1141303896745201696> Meine Bot-Rolle muss über der Joinrolle stehen\n"
            f"<:Astra_punkt:1141303896745201696> Änderungen werden sofort gespeichert"
        ))

        container.add_item(discord.ui.Separator())

        # =====================================================
        # TOGGLE BUTTON
        # =====================================================

        toggle_button = discord.ui.Button(
            label="System aktivieren" if not self.enabled else "System deaktivieren",
            emoji="<:Astra_light_on:1141303864134467675>" if not self.enabled
                  else "<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.success if not self.enabled
                  else discord.ButtonStyle.danger
        )

        async def toggle_callback(interaction: discord.Interaction):

            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            self.enabled = not self.enabled
            await self._save()

            self._build()
            await interaction.response.edit_message(view=self)

        toggle_button.callback = toggle_callback
        container.add_item(discord.ui.ActionRow(toggle_button))

        # =====================================================
        # ROLE SELECT
        # =====================================================

        role_select = discord.ui.RoleSelect(
            placeholder="🎭 Joinrolle auswählen oder ändern",
            disabled=not self.enabled
        )

        async def role_callback(interaction: discord.Interaction):

            if interaction.user.id != self.invoker.id:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Nur der Ersteller darf dieses Panel bedienen.",
                    ephemeral=True
                )

            selected_role = role_select.values[0]

            if selected_role >= self.guild.me.top_role:
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Diese Rolle ist höher oder gleich meiner Rolle.\n"
                    "Ziehe meine Rolle in den Servereinstellungen darüber.",
                    ephemeral=True
                )

            if selected_role.is_default():
                return await interaction.response.send_message(
                    "<:Astra_x:1141303954555289600> Die @everyone Rolle kann nicht verwendet werden.",
                    ephemeral=True
                )

            self.role = selected_role
            await self._save()

            self._build()
            await interaction.response.edit_message(view=self)

        role_select.callback = role_callback
        container.add_item(discord.ui.ActionRow(role_select))

        # =====================================================
        # FOOTER
        # =====================================================

        container.add_item(discord.ui.Separator())

        container.add_item(discord.ui.TextDisplay(
            f"<:Astra_support:1141303923752325210> Bedienung durch {self.invoker.mention}"
        ))

        self.add_item(container)

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

    @app_commands.command(
        name="joinrole",
        description="Verwalte die automatische Joinrolle für neue Mitglieder."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_roles=True)
    async def joinrole(self, interaction: discord.Interaction):

        guild = interaction.guild

        if not guild:
            return await interaction.response.send_message(
                "Dieser Command kann nur auf einem Server genutzt werden.",
                ephemeral=True
            )

        # ==============================
        # Daten aus DB laden
        # ==============================

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT roleID, enabled FROM joinrole WHERE guildID = %s",
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

                # Falls Rolle gelöscht wurde -> zurücksetzen
                if role is None:
                    enabled = False

        # ==============================
        # View öffnen
        # ==============================

        view = JoinRoleView(
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(joinrole(bot))