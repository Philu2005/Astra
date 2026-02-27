import discord
from discord.ext import commands
from discord import app_commands, ui
from datetime import timedelta
from typing import Literal
import asyncio

# =========================================================
# ================= AUTOMOD SETUP VIEW(Components V2) ====================
# =========================================================

class AutomodSetupView(discord.ui.LayoutView):

    TOTAL_STEPS = 4

    def __init__(self, bot: commands.Bot, invoker: discord.User):
        super().__init__(timeout=None)

        self.bot = bot
        self.invoker = invoker
        self.page = 0

        # Warn-System
        self.warn_rules: list[tuple[int, str, int | None]] = []

        # Caps
        self.caps_enabled: bool = False
        self.caps_percent: int = 50

        # Blacklist
        self.blacklist_words: list[str] = []

    def _parse_duration(self, value: str) -> int | None:
        if not value:
            return None

        value = value.lower()

        units = {
            "w": 604800,
            "d": 86400,
            "h": 3600,
            "m": 60,
            "s": 1
        }

        total_seconds = 0
        parts = value.split(",")

        for part in parts:
            part = part.strip()

            if not part:
                continue

            if len(part) < 2:
                return None

            number = part[:-1]
            unit = part[-1]

            if not number.isdigit() or unit not in units:
                return None

            total_seconds += int(number) * units[unit]

        # Discord Timeout Limit (28 Tage)
        if total_seconds <= 0 or total_seconds > 2419200:
            return None

        return total_seconds

    async def _already_configured(self, guild_id: int) -> bool:
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # Warn-System
                await cursor.execute(
                    "SELECT guildID FROM automod WHERE guildID=%s LIMIT 1",
                    (guild_id,)
                )
                warn_exists = await cursor.fetchone()

                # Caps
                await cursor.execute(
                    "SELECT guildID FROM capslock WHERE guildID=%s LIMIT 1",
                    (guild_id,)
                )
                caps_exists = await cursor.fetchone()

                # Blacklist (neue Tabellenstruktur!)
                await cursor.execute(
                    "SELECT serverID FROM blacklist_settings WHERE serverID=%s LIMIT 1",
                    (guild_id,)
                )
                blacklist_settings_exists = await cursor.fetchone()

                await cursor.execute(
                    "SELECT serverID FROM blacklist_words WHERE serverID=%s LIMIT 1",
                    (guild_id,)
                )
                blacklist_words_exists = await cursor.fetchone()

                return bool(
                    warn_exists
                    or caps_exists
                    or blacklist_settings_exists
                    or blacklist_words_exists
                )

    async def start(self, interaction: discord.Interaction) -> bool:

        exists = await self._already_configured(interaction.guild.id)

        if exists:
            red_view = discord.ui.LayoutView()

            container = discord.ui.Container(
                accent_color=discord.Colour.red().value
            )

            container.add_item(discord.ui.TextDisplay(
                "## ⚠️ Automod bereits eingerichtet\n\n"
                "Für diesen Server existiert bereits eine Konfiguration.\n\n"
                "Bitte nutze stattdessen den **/automod config** Command,\n"
                "um Einstellungen zu bearbeiten."
            ))

            red_view.add_item(container)

            await interaction.response.send_message(
                view=red_view,
                ephemeral=True
            )

            return False  # ← WICHTIG

        self._build()
        await interaction.response.send_message(
            view=self,
            ephemeral=True
        )

        return True  # ← WICHTIG

    # =========================================================
    # PROGRESS BAR
    # =========================================================

    def _progress_bar(self):
        if self.page == 0:
            return "░" * 14
        filled = int(self.page / self.TOTAL_STEPS * 14)
        return "█" * filled + "░" * (14 - filled)

    # =========================================================
    # BUILD
    # =========================================================

    def _build(self):
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Colour.orange().value
        )

        container.add_item(discord.ui.TextDisplay(
            "# 🤖 Automod Setup\n"
            f"**Schritt {self.page}/{self.TOTAL_STEPS}**\n"
            f"`{self._progress_bar()}`"
        ))
        container.add_item(discord.ui.Separator())

        # PAGE 0
        if self.page == 0:

            container.add_item(discord.ui.TextDisplay(
                "## Überblick\n\n"
                "<:Astra_punkt:1141303896745201696> **Warn-System konfigurieren**\n"
                "<:Astra_punkt:1141303896745201696> **Caps-Filter einstellen**\n"
                "<:Astra_punkt:1141303896745201696> **Blacklist verwalten**\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Alle Moderationsfunktionen werden hier zentral eingerichtet."
            ))

            container.add_item(discord.ui.Separator())

            start = discord.ui.Button(
                label="Setup starten",
                emoji="<:Astra_boost:1141303827107164270>",
                style=discord.ButtonStyle.success,
                custom_id="automod_setup_start_button"
            )

            async def start_cb(interaction):
                await self._switch(interaction, 1)

            start.callback = start_cb
            container.add_item(discord.ui.ActionRow(start))

        # PAGE 1
        elif self.page == 1:

            rules_text = (
                "\n".join(
                    f"<:Astra_punkt:1141303896745201696> "
                    f"**{warns} Warns** → {action}"
                    + (f" (`{timeout}s Timeout`)" if timeout else "")
                    for warns, action, timeout in self.warn_rules
                )
                if self.warn_rules
                else "<:Astra_x:1141303954555289600> Keine Regeln gesetzt."
            )

            container.add_item(discord.ui.TextDisplay(
                "## Warn-System\n\n"
                f"{rules_text}\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Du kannst mehrere Eskalationsstufen definieren."
            ))

            container.add_item(discord.ui.Separator())

            add_btn = discord.ui.Button(
                label="Regel hinzufügen",
                emoji="<:Astra_accept:1141303821176422460>",
                style=discord.ButtonStyle.success,
                custom_id="automod_setup_add_warn_button"
            )

            async def add_cb(interaction):

                class WarnModal(discord.ui.Modal, title="Neue Warn-Regel"):

                    warns = discord.ui.TextInput(label="Warn Grenze (1-10)")
                    action = discord.ui.TextInput(label="Aktion (Kick/Ban/Timeout)")
                    timeout_input = discord.ui.TextInput(
                        label="Timeout (optional)",
                        placeholder="z.B. 1h, 30m | w=Wochen d=Tage h=Stunden m=Min s=Sek",
                        required=False
                    )

                    def __init__(self, parent):
                        super().__init__()
                        self.parent = parent

                    async def on_submit(self, inter):

                        try:
                            warns_val = int(self.warns.value)
                        except:
                            return await inter.response.send_message(
                                "<:Astra_x:1141303954555289600> Ungültige Warn-Zahl.",
                                ephemeral=True
                            )

                        timeout_val = None

                        if self.timeout_input.value:
                            timeout_val = self.parent._parse_duration(self.timeout_input.value)

                            if timeout_val is None:
                                return await inter.response.send_message(
                                    "<:Astra_x:1141303954555289600> Ungültiges Zeitformat. Nutze z.B. 1w, 1d, 2h, 3m oder 4s.",
                                    ephemeral=True
                                )

                        self.parent.warn_rules.append(
                            (warns_val, self.action.value.strip().capitalize(), timeout_val)
                        )

                        self.parent._build()
                        await inter.response.edit_message(view=self.parent)

                await interaction.response.send_modal(WarnModal(self))

            add_btn.callback = add_cb
            container.add_item(discord.ui.ActionRow(add_btn))

        # PAGE 2
        elif self.page == 2:

            active = self.caps_enabled

            status_emoji = (
                "<:Astra_accept:1141303821176422460>"
                if active else
                "<:Astra_x:1141303954555289600>"
            )

            status_text = "Aktiv" if active else "Deaktiviert"

            toggle_label = "Ein" if not active else "Aus"
            toggle_style = (
                discord.ButtonStyle.success
                if not active else
                discord.ButtonStyle.danger
            )

            toggle_btn = discord.ui.Button(
                label=toggle_label,
                style=toggle_style,
                custom_id="automod_setup_toggle_button_1"
            )

            async def toggle_cb(interaction):
                self.caps_enabled = not self.caps_enabled
                self._build()
                await interaction.response.edit_message(view=self)

            toggle_btn.callback = toggle_cb

            section = discord.ui.Section(
                discord.ui.TextDisplay(
                    "## Caps-Filter\n\n"
                    f"{status_emoji} **Status:** {status_text}\n"
                    f"<:Astra_punkt:1141303896745201696> "
                    f"Limit: **{self.caps_percent}% Großbuchstaben**\n\n"
                    "<:Astra_light_on:1141303864134467675> "
                    "Nach Überschreitung wird die Nachricht gelöscht."
                ),
                accessory=toggle_btn
            )

            container.add_item(section)
            container.add_item(discord.ui.Separator())

            percent_select = discord.ui.Select(
                placeholder="Caps-Limit ändern",
                options=[
                    discord.SelectOption(label=f"{i}%", value=str(i))
                    for i in range(10, 101, 10)
                ],
                custom_id="automod_setup_percent_select"
            )

            async def percent_cb(interaction):
                self.caps_percent = int(percent_select.values[0])
                self._build()
                await interaction.response.edit_message(view=self)

            percent_select.callback = percent_cb
            container.add_item(discord.ui.ActionRow(percent_select))

        # PAGE 3
        elif self.page == 3:

            words_text = (
                "\n".join(
                    f"<:Astra_punkt:1141303896745201696> `{w}`"
                    for w in self.blacklist_words
                )
                if self.blacklist_words
                else "<:Astra_x:1141303954555289600> Keine Wörter gesetzt."
            )

            container.add_item(discord.ui.TextDisplay(
                "## Blacklist\n\n"
                f"{words_text}\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Mehrere Wörter mit `,` trennen."
            ))

            container.add_item(discord.ui.Separator())

            add_btn = discord.ui.Button(
                label="Wörter hinzufügen",
                emoji="<:Astra_accept:1141303821176422460>",
                style=discord.ButtonStyle.primary,
                custom_id="automod_setup_add_blacklist_button"
            )

            async def add_cb(interaction):

                class WordModal(discord.ui.Modal, title="Blacklist Wörter"):

                    words = discord.ui.TextInput(
                        label="Wörter (mit , trennen)"
                    )

                    def __init__(self, parent):
                        super().__init__()
                        self.parent = parent

                    async def on_submit(self, inter):

                        entries = [
                            w.strip().lower()
                            for w in self.words.value.split(",")
                            if w.strip()
                        ]

                        self.parent.blacklist_words.extend(entries)
                        self.parent._build()
                        await inter.response.edit_message(view=self.parent)

                await interaction.response.send_modal(WordModal(self))

            add_btn.callback = add_cb
            container.add_item(discord.ui.ActionRow(add_btn))

        # PAGE 4
        elif self.page == 4:

            container.add_item(discord.ui.TextDisplay(
                "## Abschluss & Übersicht\n\n"
                f"<:Astra_punkt:1141303896745201696> "
                f"Warn-Regeln: **{len(self.warn_rules)}**\n"
                f"<:Astra_punkt:1141303896745201696> "
                f"Caps: **{'Aktiv' if self.caps_enabled else 'Deaktiviert'} "
                f"({self.caps_percent}%)**\n"
                f"<:Astra_punkt:1141303896745201696> "
                f"Blacklist: **{len(self.blacklist_words)} Wörter**\n\n"
                "<:Astra_accept:1141303821176422460> "
                "Wenn alles korrekt ist, kann gespeichert werden."
            ))

            container.add_item(discord.ui.Separator())

            save = discord.ui.Button(
                label="Automod speichern",
                emoji="<:Astra_accept:1141303821176422460>",
                style=discord.ButtonStyle.success,
                custom_id="automod_setup_save_button"
            )

            async def save_cb(interaction):

                if interaction.user.id != self.invoker.id:
                    return await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> "
                        "Nur der Ersteller darf speichern.",
                        ephemeral=True
                    )

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cursor:

                        await cursor.execute(
                            "DELETE FROM automod WHERE guildID=%s",
                            (interaction.guild.id,)
                        )

                        await cursor.execute(
                            "DELETE FROM capslock WHERE guildID=%s",
                            (interaction.guild.id,)
                        )

                        await cursor.execute(
                            "DELETE FROM blacklist_settings WHERE serverID=%s",
                            (interaction.guild.id,)
                        )

                        await cursor.execute(
                            "DELETE FROM blacklist_words WHERE serverID=%s",
                            (interaction.guild.id,)
                        )

                        for warns, action, timeout in self.warn_rules:
                            await cursor.execute(
                                "INSERT INTO automod "
                                "(guildID, warns, action, timeout_seconds) "
                                "VALUES (%s,%s,%s,%s)",
                                (interaction.guild.id, warns, action, timeout)
                            )

                        if self.caps_enabled:
                            await cursor.execute(
                                "INSERT INTO capslock (guildID, percent, status) "
                                "VALUES (%s,%s,%s)",
                                (interaction.guild.id, self.caps_percent, 1)
                            )

                        if self.blacklist_words:
                            await cursor.execute(
                                "INSERT INTO blacklist_settings (serverID, status) "
                                "VALUES (%s,%s)",
                                (interaction.guild.id, 1)
                            )

                            for word in self.blacklist_words:
                                await cursor.execute(
                                    "INSERT INTO blacklist_words (serverID, word) "
                                    "VALUES (%s,%s)",
                                    (interaction.guild.id, word)
                                )

                success_view = discord.ui.LayoutView()

                success_container = discord.ui.Container(
                    accent_color=discord.Colour.green().value
                )

                success_container.add_item(discord.ui.TextDisplay(
                    "## <:Astra_accept:1141303821176422460> Automod eingerichtet\n\n"
                    "Die Konfiguration wurde erfolgreich gespeichert.\n\n"
                    "Alle Moderationsfunktionen sind nun aktiv."
                ))

                success_view.add_item(success_container)

                await interaction.response.defer()
                await interaction.edit_original_response(view=success_view)

            save.callback = save_cb
            container.add_item(discord.ui.ActionRow(save))

        nav = []

        if self.page > 0:
            back = discord.ui.Button(
                label="Zurück",
                emoji="<:Astra_arrow_backwards:1392540551546671348>",
                style=discord.ButtonStyle.secondary,
                custom_id="automod_setup_back_button"
            )

            async def back_cb(interaction):
                await self._switch(interaction, self.page - 1)

            back.callback = back_cb
            nav.append(back)

        if self.page < self.TOTAL_STEPS:
            nxt = discord.ui.Button(
                label="Weiter",
                emoji="<:Astra_arrow:1141303823600717885>",
                style=discord.ButtonStyle.primary,
                custom_id="automod_setup_next_button"
            )

            async def next_cb(interaction):
                await self._switch(interaction, self.page + 1)

            nxt.callback = next_cb
            nav.append(nxt)

        cancel = discord.ui.Button(
            label="Abbrechen",
            emoji="<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.danger,
            custom_id="automod_setup_cancel_button"
        )

        async def cancel_cb(interaction):
            await interaction.response.defer()
            await interaction.delete_original_response()

        cancel.callback = cancel_cb
        nav.append(cancel)

        container.add_item(discord.ui.ActionRow(*nav))
        self.add_item(container)

    async def _switch(self, interaction, page: int):
        self.page = page
        self._build()
        await interaction.response.edit_message(view=self)


class AutomodConfigView(discord.ui.LayoutView):

    def __init__(self, bot: commands.Bot, invoker: discord.User, guild: discord.Guild):
        super().__init__(timeout=None)

        self.bot = bot
        self.invoker = invoker
        self.guild = guild

        self.warn_rules: list[tuple[int, str, int | None]] = []
        self.caps_percent: int | None = None
        self.words: list[str] = []

    def _parse_duration(self, value: str) -> int | None:
        if not value:
            return None

        value = value.lower()

        units = {
            "w": 604800,
            "d": 86400,
            "h": 3600,
            "m": 60,
            "s": 1
        }

        total_seconds = 0
        parts = value.split(",")

        for part in parts:
            part = part.strip()

            if not part:
                continue

            if len(part) < 2:
                return None

            number = part[:-1]
            unit = part[-1]

            if not number.isdigit() or unit not in units:
                return None

            total_seconds += int(number) * units[unit]

        # Discord Timeout Limit (28 Tage)
        if total_seconds <= 0 or total_seconds > 2419200:
            return None

        return total_seconds

    # =========================================================
    # START
    # =========================================================

    async def start(self, interaction: discord.Interaction):
        await self._load_data()
        self._build()
        await interaction.response.send_message(view=self, ephemeral=True)

    # =========================================================
    # LOAD DATA
    # =========================================================

    async def _load_data(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # =========================================================
                # WARN SYSTEM
                # =========================================================

                await cursor.execute(
                    "SELECT warns, action, timeout_seconds "
                    "FROM automod WHERE guildID=%s",
                    (self.guild.id,)
                )
                self.warn_rules = await cursor.fetchall() or []

                # =========================================================
                # CAPSLOCK
                # =========================================================

                await cursor.execute(
                    "SELECT percent, status FROM capslock WHERE guildID=%s",
                    (self.guild.id,)
                )
                caps = await cursor.fetchone()

                if caps:
                    self.caps_percent = caps[0]
                    self.caps_status = caps[1]
                else:
                    # Defaultwerte wenn noch kein Eintrag existiert
                    self.caps_percent = 50
                    self.caps_status = 0

                # =========================================================
                # BLACKLIST
                # =========================================================

                # Status laden
                await cursor.execute(
                    "SELECT status FROM blacklist_settings WHERE serverID=%s",
                    (self.guild.id,)
                )
                row = await cursor.fetchone()

                if row:
                    self.blacklist_status = row[0]
                else:
                    self.blacklist_status = 0

                # Wörter laden
                await cursor.execute(
                    "SELECT word FROM blacklist_words WHERE serverID=%s",
                    (self.guild.id,)
                )
                words = await cursor.fetchall()
                self.words = [w[0] for w in words] if words else []

    # =========================================================
    # PERMISSION CHECK
    # =========================================================

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> "
                "Nur der Command-Ersteller darf dieses Panel bedienen.",
                ephemeral=True
            )
            return False
        return True

    # =========================================================
    # BUILD
    # =========================================================

    def _build(self):
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Colour.blurple().value
        )

        # =====================================================
        # HEADER SECTION
        # =====================================================

        container.add_item(discord.ui.TextDisplay(
            "# ⚙️ Automod Konfiguration\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Hier kannst du bestehende Moderations-Regeln anpassen."
        ))

        container.add_item(discord.ui.Separator())

        # =====================================================
        # WARN SYSTEM
        # =====================================================

        warn_text = (
            "\n".join(
                f"<:Astra_punkt:1141303896745201696> "
                f"**{w} Warns** → {a}"
                + (f" (`{t}s Timeout`)" if t else "")
                for w, a, t in self.warn_rules
            )
            if self.warn_rules
            else "<:Astra_x:1141303954555289600> Keine Regeln gesetzt."
        )

        container.add_item(discord.ui.TextDisplay(
            "## Warn-System\n\n"
            f"{warn_text}\n\n"
            "<:Astra_light_on:1141303864134467675> "
            "Regeln werden bei Erreichen der Warn-Grenze ausgelöst."
        ))

        container.add_item(discord.ui.Separator())

        add_rule = discord.ui.Button(
            label="Regel hinzufügen",
            emoji="<:Astra_accept:1141303821176422460>",
            style=discord.ButtonStyle.success,
            custom_id="automod_config_add_rule_button"
        )

        remove_rule = discord.ui.Button(
            label="Regel entfernen",
            emoji="<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.danger,
            custom_id="automod_config_remove_rule_button"
        )

        async def add_rule_cb(interaction):

            class RuleModal(discord.ui.Modal, title="Neue Warn-Regel"):

                warns = discord.ui.TextInput(label="Warn Grenze (1-10)")
                action = discord.ui.TextInput(label="Aktion (Kick/Ban/Timeout)")
                timeout_input = discord.ui.TextInput(
                    label="Timeout (optional)",
                    placeholder="z.B. 1h, 30m | w=Wochen d=Tage h=Stunden m=Min s=Sek",
                    required=False
                )

                def __init__(self, parent):
                    super().__init__()
                    self.parent = parent

                async def on_submit(self, inter):

                    timeout_val = None

                    if self.timeout_input.value:
                        timeout_val = self.parent._parse_duration(self.timeout_input.value)

                        if timeout_val is None:
                            return await inter.response.send_message(
                                "<:Astra_x:1141303954555289600> Ungültiges Zeitformat. Nutze z.B. 1w, 1d, 2h, 3m oder 4s.",
                                ephemeral=True
                            )

                    async with self.parent.bot.pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            await cursor.execute(
                                "INSERT INTO automod "
                                "(guildID, warns, action, timeout_seconds) "
                                "VALUES (%s,%s,%s,%s)",
                                (
                                    self.parent.guild.id,
                                    self.warns.value,
                                    self.action.value,
                                    timeout_val
                                )
                            )

                    await self.parent.refresh_view(inter)

            await interaction.response.send_modal(RuleModal(self))

        async def remove_rule_cb(interaction):

            class RemoveModal(discord.ui.Modal, title="Warn-Regel entfernen"):

                warns = discord.ui.TextInput(label="Warn Grenze")

                def __init__(self, parent):
                    super().__init__()
                    self.parent = parent

                async def on_submit(self, inter):
                    async with self.parent.bot.pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            await cursor.execute(
                                "DELETE FROM automod "
                                "WHERE guildID=%s AND warns=%s",
                                (self.parent.guild.id, self.warns.value)
                            )

                    await self.parent.refresh_view(inter)

            await interaction.response.send_modal(RemoveModal(self))

        add_rule.callback = add_rule_cb
        remove_rule.callback = remove_rule_cb

        container.add_item(discord.ui.ActionRow(add_rule, remove_rule))
        container.add_item(discord.ui.Separator())

        # =====================================================
        # CAPS FILTER
        # =====================================================

        # Status und Prozent aus geladenen Daten
        caps_enabled = getattr(self, "caps_status", 0) == 1
        current_percent = self.caps_percent if self.caps_percent is not None else 50

        status_emoji = (
            "<:Astra_accept:1141303821176422460>"
            if caps_enabled else
            "<:Astra_x:1141303954555289600>"
        )

        status_text = "Aktiv" if caps_enabled else "Deaktiviert"

        toggle_label = "Aus" if caps_enabled else "Ein"
        toggle_style = (
            discord.ButtonStyle.danger
            if caps_enabled else
            discord.ButtonStyle.success
        )

        toggle_btn = discord.ui.Button(
            label=toggle_label,
            style=toggle_style,
            custom_id="automod_config_toggle_button_1"
        )

        # ---------- TOGGLE STATUS ----------

        async def toggle_caps(interaction):

            new_status = 0 if caps_enabled else 1

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:

                    # Prüfen ob Eintrag existiert
                    await cursor.execute(
                        "SELECT guildID FROM capslock WHERE guildID=%s",
                        (self.guild.id,)
                    )
                    exists = await cursor.fetchone()

                    if exists:
                        # Nur Status ändern
                        await cursor.execute(
                            "UPDATE capslock SET status=%s WHERE guildID=%s",
                            (new_status, self.guild.id)
                        )
                    else:
                        # Neu anlegen mit Default-Prozent
                        await cursor.execute(
                            "INSERT INTO capslock (guildID, percent, status) VALUES (%s,%s,%s)",
                            (self.guild.id, current_percent, new_status)
                        )

            await self.refresh_view(interaction)

        toggle_btn.callback = toggle_caps

        # ---------- SECTION ----------

        section = discord.ui.Section(
            discord.ui.TextDisplay(
                "## Caps-Filter\n\n"
                f"{status_emoji} **Status:** {status_text}\n"
                f"<:Astra_punkt:1141303896745201696> "
                f"Limit: **{current_percent}%**\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Nach Überschreitung wird die Nachricht entfernt."
            ),
            accessory=toggle_btn
        )

        container.add_item(section)

        # ---------- SELECT MENU (NUR WENN AKTIV) ----------

        if caps_enabled:
            options = [
                discord.SelectOption(
                    label=f"{i}%",
                    value=str(i),
                    default=(current_percent == i)
                )
                for i in range(10, 101, 10)
            ]

            percent_select = discord.ui.Select(
                placeholder="Prozent wählen...",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="automod_config_percent_select"
            )

            async def percent_select_cb(interaction):
                value = int(percent_select.values[0])

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            "UPDATE capslock SET percent=%s WHERE guildID=%s",
                            (value, self.guild.id)
                        )

                await self.refresh_view(interaction)

            percent_select.callback = percent_select_cb

            container.add_item(discord.ui.ActionRow(percent_select))

        container.add_item(discord.ui.Separator())

        # =====================================================
        # BLACKLIST
        # =====================================================

        # Status aus _load_data()
        blacklist_enabled = getattr(self, "blacklist_status", 0) == 1

        # Wörter aus blacklist_words
        real_words = sorted(self.words)

        status_emoji = (
            "<:Astra_accept:1141303821176422460>"
            if blacklist_enabled else
            "<:Astra_x:1141303954555289600>"
        )

        status_text = "Aktiv" if blacklist_enabled else "Deaktiviert"

        words_text = (
            "\n".join(
                f"<:Astra_punkt:1141303896745201696> `{w}`"
                for w in real_words
            )
            if real_words
            else "<:Astra_x:1141303954555289600> Keine Wörter gesetzt."
        )

        # ---------- TOGGLE BUTTON ----------

        toggle_label = "Aus" if blacklist_enabled else "Ein"
        toggle_style = (
            discord.ButtonStyle.danger
            if blacklist_enabled else
            discord.ButtonStyle.success
        )

        toggle_blacklist = discord.ui.Button(
            label=toggle_label,
            style=toggle_style,
            custom_id="automod_config_toggle_button_2"
        )

        async def toggle_blacklist_cb(interaction):

            new_status = 0 if blacklist_enabled else 1

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO blacklist_settings (serverID, status) "
                        "VALUES (%s,%s) "
                        "ON DUPLICATE KEY UPDATE status=%s",
                        (self.guild.id, new_status, new_status)
                    )

            await self.refresh_view(interaction)

        toggle_blacklist.callback = toggle_blacklist_cb

        # ---------- SECTION ----------

        blacklist_section = discord.ui.Section(
            discord.ui.TextDisplay(
                "## Blacklist\n\n"
                f"{status_emoji} Status: **{status_text}**\n\n"
                f"{words_text}\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Nachrichten mit diesen Wörtern werden automatisch gelöscht."
            ),
            accessory=toggle_blacklist
        )

        container.add_item(blacklist_section)
        container.add_item(discord.ui.Separator())

        # ---------- BUTTONS ----------

        add_word = discord.ui.Button(
            label="Wörter hinzufügen",
            emoji="<:Astra_accept:1141303821176422460>",
            style=discord.ButtonStyle.success,
            disabled=not blacklist_enabled,
            custom_id="automod_config_add_word_button"
        )

        remove_word = discord.ui.Button(
            label="Wort entfernen",
            emoji="<:Astra_x:1141303954555289600>",
            style=discord.ButtonStyle.danger,
            disabled=not blacklist_enabled,
            custom_id="automod_config_remove_word_button"
        )

        # ---------- ADD WORD ----------

        async def add_word_cb(interaction):

            class AddWord(discord.ui.Modal, title="Blacklist Wörter hinzufügen"):
                words = discord.ui.TextInput(
                    label="Wörter (mit , trennen)"
                )

                def __init__(self, parent):
                    super().__init__()
                    self.parent = parent

                async def on_submit(self, inter):
                    entries = [
                        w.strip().lower()
                        for w in self.words.value.split(",")
                        if w.strip()
                    ]

                    async with self.parent.bot.pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            for word in entries:
                                await cursor.execute(
                                    "INSERT IGNORE INTO blacklist_words (serverID, word) "
                                    "VALUES (%s,%s)",
                                    (self.parent.guild.id, word)
                                )

                    await self.parent.refresh_view(inter)

            await interaction.response.send_modal(AddWord(self))

        # ---------- REMOVE WORD ----------

        async def remove_word_cb(interaction):

            class RemoveWord(discord.ui.Modal, title="Blacklist Wort entfernen"):
                word = discord.ui.TextInput(label="Wort")

                def __init__(self, parent):
                    super().__init__()
                    self.parent = parent

                async def on_submit(self, inter):
                    async with self.parent.bot.pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            await cursor.execute(
                                "DELETE FROM blacklist_words "
                                "WHERE serverID=%s AND word=%s",
                                (self.parent.guild.id, self.word.value.lower())
                            )

                    await self.parent.refresh_view(inter)

            await interaction.response.send_modal(RemoveWord(self))

        add_word.callback = add_word_cb
        remove_word.callback = remove_word_cb

        container.add_item(discord.ui.ActionRow(add_word, remove_word))
        self.add_item(container)

    # =========================================================
    # REFRESH
    # =========================================================

    async def refresh_view(self, interaction: discord.Interaction):
        await self._load_data()
        self._build()
        await interaction.response.edit_message(view=self)


@app_commands.guild_only()
class Automod(app_commands.Group):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__(
            name="automod",
            description="Konfiguriere das Automod-System"
        )

    # =====================================================
    # SETUP
    # =====================================================

    @app_commands.command(
        name="setup",
        description="Starte das interaktive Automod Setup."
    )
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):

        view = AutomodSetupView(self.bot, interaction.user)
        started = await view.start(interaction)

        if not started:
            return  # ← KEIN Modlog senden

        # ── MODLOG ──
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT channelID FROM modlog WHERE serverID = %s",
                    (interaction.guild.id,)
                )
                modlog = await cursor.fetchone()

                if modlog:
                    channel = interaction.guild.get_channel(int(modlog[0]))
                    if channel:
                        embed = discord.Embed(
                            title="⚙️ Automod Setup gestartet",
                            description=f"{interaction.user} (`{interaction.user.id}`) hat das Setup gestartet.",
                            colour=discord.Colour.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        await channel.send(embed=embed)

    # =====================================================
    # CONFIG
    # =====================================================

    @app_commands.command(
        name="config",
        description="Öffne das Automod Kontrollpanel."
    )
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config(self, interaction: discord.Interaction):

        view = AutomodConfigView(
            self.bot,
            interaction.user,
            interaction.guild
        )

        await view.start(interaction)

        # ── MODLOG ──
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT channelID FROM modlog WHERE serverID = %s",
                    (interaction.guild.id,)
                )
                modlog = await cursor.fetchone()

                if modlog:
                    channel = interaction.guild.get_channel(int(modlog[0]))
                    if channel:
                        embed = discord.Embed(
                            title="⚙️ Automod Config geöffnet",
                            description=f"{interaction.user} (`{interaction.user.id}`) hat das Config-Panel geöffnet.",
                            colour=discord.Colour.blurple(),
                            timestamp=discord.utils.utcnow()
                        )
                        await channel.send(embed=embed)

    # =====================================================
    # RESET
    # =====================================================

    @app_commands.command(
        name="reset",
        description="Setze das gesamte Automod-System zurück."
    )
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):

        class ConfirmReset(ui.View):

            def __init__(self, bot):
                super().__init__(timeout=30)
                self.bot = bot

            @ui.button(label="Bestätigen", style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, button: ui.Button):

                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            "DELETE FROM automod WHERE guildID=%s",
                            (inter.guild.id,)
                        )
                        await cursor.execute(
                            "DELETE FROM capslock WHERE guildID=%s",
                            (inter.guild.id,)
                        )
                        await cursor.execute(
                            "DELETE FROM blacklist_settings WHERE serverID=%s",
                            (inter.guild.id,)
                        )
                        await cursor.execute(
                            "DELETE FROM blacklist_words WHERE serverID=%s",
                            (inter.guild.id,)
                        )

                await inter.response.edit_message(
                    content="🗑️ Automod wurde vollständig zurückgesetzt.",
                    view=None
                )

                # ── MODLOG ──
                async with self.bot.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            "SELECT channelID FROM modlog WHERE serverID = %s",
                            (inter.guild.id,)
                        )
                        modlog = await cursor.fetchone()

                        if modlog:
                            channel = inter.guild.get_channel(int(modlog[0]))
                            if channel:
                                embed = discord.Embed(
                                    title="🗑️ Automod Reset",
                                    description=f"{inter.user} (`{inter.user.id}`) hat Automod zurückgesetzt.",
                                    colour=discord.Colour.red(),
                                    timestamp=discord.utils.utcnow()
                                )
                                await channel.send(embed=embed)

            @ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, button: ui.Button):
                await inter.response.edit_message(
                    content="Reset abgebrochen.",
                    view=None
                )

        await interaction.response.send_message(
            "⚠️ Möchtest du wirklich ALLE Automod-Regeln löschen?",
            view=ConfirmReset(self.bot),
            ephemeral=True
        )
# =========================================================
# ===================== AUTOMOD COG =======================
# =========================================================



class Warn(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg):

        if msg.author.bot:
            return

        if not msg.guild:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # =====================================================
                # ================= CAPS FILTER =======================
                # =====================================================

                if msg.author.id != msg.guild.owner.id:

                    await cursor.execute(
                        "SELECT percent FROM capslock WHERE guildID = (%s)",
                        (msg.guild.id,)
                    )
                    result = await cursor.fetchone()

                    if result:
                        percent1 = result[0]

                        upper = 0
                        for char in msg.content:
                            if char.isupper():
                                pass
                            else:
                                upper += 1

                        if len(msg.content) >= 6:

                            multiplication = 100 / len(msg.content)
                            procent = (len(msg.content) - upper) * multiplication

                            if int(percent1) < round(procent):

                                channel = self.bot.get_channel(msg.channel.id)
                                message = await channel.fetch_message(msg.id)

                                embed = discord.Embed(
                                    title="Bitte unterlasse übermäßige Caps!",
                                    description=f"Die Nachricht hatte `{round(procent)}%` Caps!\nDu wurdest verwarnt {msg.author.mention}!",
                                    colour=discord.Colour.blue(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.set_author(name=msg.author, icon_url=msg.author.avatar)
                                embed.add_field(
                                    name=f"User: {msg.author}",
                                    value=f"Nachricht: {msg.content}"
                                )
                                embed.set_footer(
                                    text=f"User: {msg.author} | ID: {msg.author.id}"
                                )

                                await msg.channel.send(embed=embed)
                                await message.delete()

                                await cursor.execute(
                                    "SELECT reason FROM warns WHERE userID = (%s) AND guildID = (%s)",
                                    (msg.author.id, msg.guild.id)
                                )
                                result2 = await cursor.fetchall()

                                reason = (
                                    f"{msg.author.name} überschritt das Caps Limit von "
                                    f"`{int(percent1)}%`. Die Nachricht hatte `{round(procent)}%` Caps!"
                                )

                                if result2 == ():
                                    await cursor.execute(
                                        "INSERT INTO warns (guildID, userID, reason, warnID) VALUES (%s, %s, %s, %s)",
                                        (msg.guild.id, msg.author.id, reason, 1)
                                    )
                                else:
                                    await cursor.execute(
                                        "INSERT INTO warns (guildID, userID, reason, warnID) VALUES (%s, %s, %s, %s)",
                                        (msg.guild.id, msg.author.id, reason, len(result2) + 1)
                                    )

                                await cursor.execute(
                                    "SELECT channelID FROM modlog WHERE serverID = (%s)",
                                    (msg.guild.id,)
                                )
                                result3 = await cursor.fetchone()

                                if result3 is not None:
                                    channel = msg.guild.get_channel(int(result3[0]))

                                    embed = discord.Embed(
                                        colour=discord.Colour.orange(),
                                        description=f"Der User {msg.author} (`{msg.author.id}`) wurde verwarnt."
                                    )
                                    embed.add_field(
                                        name="👤 User:",
                                        value=f"{msg.author.mention}",
                                        inline=False
                                    )
                                    embed.add_field(
                                        name="👮 Moderator:",
                                        value=f"{self.bot.user} (`{self.bot.user.id}`)",
                                        inline=False
                                    )
                                    embed.add_field(
                                        name="📄 Grund:",
                                        value=f"{reason}",
                                        inline=False
                                    )
                                    embed.set_author(
                                        name=msg.author,
                                        icon_url=msg.author.avatar
                                    )

                                    await channel.send(embed=embed)

                # =====================================================
                # ================= BLACKLIST =========================
                # =====================================================

                await cursor.execute(
                    "SELECT status FROM blacklist_settings WHERE serverID = (%s)",
                    (msg.guild.id,)
                )
                status_row = await cursor.fetchone()

                if not status_row or status_row[0] != 1:
                    return

                await cursor.execute(
                    "SELECT word FROM blacklist_words WHERE serverID = (%s)",
                    (msg.guild.id,)
                )
                result = await cursor.fetchall()

                if not result:
                    return

                for eintrag in result:

                    word = eintrag[0]
                    lowerword = word.lower()
                    lowercontent = msg.content.lower()

                    if lowerword in lowercontent:

                        embed = discord.Embed(
                            title="Bitte unterlasse die Schimpfwörter!",
                            description=f"{msg.author.mention} nutze ein Wort: ``{word}`` welches hier nicht erlaubt ist!",
                            colour=discord.Colour.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.set_author(name=msg.author, icon_url=msg.author.avatar)

                        delete = await msg.channel.send(embed=embed)

                        channel = msg.channel
                        message = await channel.fetch_message(msg.id)
                        await message.delete()

                        # ================= MODLOG BLACKLIST =================

                        await cursor.execute(
                            "SELECT channelID FROM modlog WHERE serverID = (%s)",
                            (msg.guild.id,)
                        )
                        result_modlog = await cursor.fetchone()

                        if result_modlog is not None:
                            log_channel = msg.guild.get_channel(int(result_modlog[0]))

                            log_embed = discord.Embed(
                                colour=discord.Colour.orange(),
                                description=f"Der User {msg.author} (`{msg.author.id}`) nutzte ein verbotenes Wort."
                            )
                            log_embed.add_field(
                                name="👤 User:",
                                value=f"{msg.author.mention}",
                                inline=False
                            )
                            log_embed.add_field(
                                name="📄 Wort:",
                                value=f"{word}",
                                inline=False
                            )
                            log_embed.add_field(
                                name="🔔 Auslöser:",
                                value="Blacklist",
                                inline=False
                            )
                            log_embed.set_author(
                                name=msg.author,
                                icon_url=msg.author.avatar
                            )

                            await log_channel.send(embed=log_embed)

                        await asyncio.sleep(7)
                        await delete.delete()

    @app_commands.command(name="warn", description="Warne einen User.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        """Warne einen User."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # ─────────────────────────────
                # WARN COUNT HOLEN
                # ─────────────────────────────
                await cursor.execute(
                    "SELECT COUNT(*) FROM warns WHERE userID=%s AND guildID=%s",
                    (member.id, interaction.guild.id)
                )
                count_row = await cursor.fetchone()
                current_warns = count_row[0] if count_row else 0

                warnid = current_warns + 1

                await cursor.execute(
                    "INSERT INTO warns (guildID, userID, reason, warnID) VALUES (%s,%s,%s,%s)",
                    (interaction.guild.id, member.id, reason, warnid)
                )

                # ─────────────────────────────
                # RESPONSE EMBED
                # ─────────────────────────────
                title = "Neue Verwarnung" if warnid == 1 else "Verwarnung hinzugefügt"

                embed = discord.Embed(
                    title=title,
                    description=(
                        f"Der User {member.mention} wurde mit der Warn-ID ``{warnid}``\n\n"
                        f"📄 **Grund:** `{reason}`\n\n"
                        f"Nutze `/warn`, um weitere Verwarnungen zu vergeben."
                    ),
                    color=discord.Color.red()
                )

                await interaction.response.send_message(embed=embed)

                # ─────────────────────────────
                # MODLOG
                # ─────────────────────────────
                await cursor.execute(
                    "SELECT channelID FROM modlog WHERE serverID=%s",
                    (interaction.guild.id,)
                )
                modlog = await cursor.fetchone()

                if modlog:
                    channel = interaction.guild.get_channel(int(modlog[0]))
                    if channel:
                        log_embed = discord.Embed(
                            colour=discord.Colour.orange(),
                            description=f"{member} (`{member.id}`) wurde verwarnt."
                        )
                        log_embed.add_field(name="👤 Member", value=member.mention, inline=False)
                        log_embed.add_field(
                            name="👮 Moderator",
                            value=f"{interaction.user} (`{interaction.user.id}`)",
                            inline=False
                        )
                        log_embed.add_field(name="📄 Grund", value=reason, inline=False)
                        log_embed.set_author(name=member, icon_url=member.avatar)
                        await channel.send(embed=log_embed)

                # ─────────────────────────────
                # AUTOMOD CHECK (ESKALIEREND)
                # ─────────────────────────────
                await cursor.execute(
                    "SELECT action, warns, timeout_seconds FROM automod WHERE guildID=%s",
                    (interaction.guild.id,)
                )
                rules = await cursor.fetchall()

                if not rules:
                    return

                # höchste Regel zuerst
                rules = sorted(rules, key=lambda x: int(x[1]), reverse=True)

                for action, warn_limit, timeout_seconds in rules:
                    if warnid >= int(warn_limit):

                        # Automod Log
                        if modlog:
                            channel = interaction.guild.get_channel(int(modlog[0]))
                            if channel:
                                auto_embed = discord.Embed(
                                    title="🤖 Automod ausgelöst",
                                    colour=discord.Colour.dark_orange(),
                                    timestamp=discord.utils.utcnow()
                                )
                                auto_embed.add_field(name="👤 Member", value=member.mention, inline=False)
                                auto_embed.add_field(
                                    name="📊 Verwarnungen",
                                    value=f"{warnid} / {warn_limit}",
                                    inline=True
                                )
                                auto_embed.add_field(name="⚙️ Aktion", value=action, inline=True)
                                auto_embed.add_field(name="🔔 Auslöser", value="Warn-System", inline=False)
                                await channel.send(embed=auto_embed)

                        # Aktion ausführen (nur höchste!)
                        if action == "Kick":
                            await member.kick(reason="Automod")

                        elif action == "Ban":
                            await member.ban(reason="Automod")

                        elif action == "Timeout":
                            duration = timeout_seconds if timeout_seconds else 30
                            await member.timeout(
                                timedelta(seconds=int(duration)),
                                reason="Automod"
                            )

                        break  # ← nur höchste Regel!

    @app_commands.command(name="unwarn", description="Entferne Warns von einem User.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, member: discord.Member, warnid: int):
        """Entferne Warns von einem User."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM warns WHERE guildID=%s AND warnID=%s AND userID=%s",
                    (interaction.guild.id, warnid, member.id)
                )

                if cursor.rowcount > 0:
                    embed = discord.Embed(
                        title="Verwarnung gelöscht",
                        description=(
                            f"Die Verwarnung des Users {member.mention} mit der ID: ``{warnid}`` "
                            f"wurde gelöscht.\nUm jemanden zu warnen nutze `/warn`."
                        ),
                        color=discord.Color.green()
                    )
                else:
                    embed = discord.Embed(
                        title="Keine Aktuellen erwarnungen",
                        description=(
                            f"Es gibt aktuell keine Verwarnungen für den User {member.mention} "
                            f"mit der WarnID: ``{warnid}``!\nUm jemanden zu warnen nutze `/warn`."
                        ),
                        color=discord.Color.green()
                    )

                await interaction.response.send_message(embed=embed)

    @app_commands.command(name="warns", description="Erhalte eine Liste mit allen Warns eines Users.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warns(self, interaction: discord.Interaction, member: discord.Member):
        """Erhalte eine Liste mit allen Warns eines Users."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT reason, warnID FROM warns WHERE guildID=%s AND userID=%s",
                    (interaction.guild.id, member.id)
                )
                result = await cursor.fetchall()

                if not result:
                    embed = discord.Embed(
                        title=f"Verwarnungen für {member.name}, {member.id}",
                        description=(
                            f"Der User {member.name} hat keine Verwarnungen.\n"
                            f"Um jemanden zu warnen nutze `/warn`."
                        ),
                        color=discord.Color.blue()
                    )
                else:
                    embed = discord.Embed(
                        title=f"Verwarnungen für {member.name}, {member.id}",
                        description=(
                            "Um jemanden zu warnen nutze `/warn`.\n"
                            "Um jemanden eine Verwarnung zu entfernen nutze `/unwarn`."
                        ),
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)

                    for reason, warnID in result:
                        embed.add_field(
                            name=f"WarnID: {warnID}",
                            value=f"Grund: {reason}",
                            inline=True
                        )

                await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Warn(bot))
    bot.tree.add_command(Automod(bot))