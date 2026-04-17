import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View
from datetime import datetime


class WebsiteButton(discord.ui.Button):
    def __init__(self):
        # Link-Buttons brauchen keinen custom_id und sind automatisch "persistierbar"
        super().__init__(label="🌐 Website", style=discord.ButtonStyle.link, url="https://astra-bot.de")


class Dropdown(discord.ui.Select):
    def __init__(self, cog: commands.Cog):
        options = [
            # Administration / Moderation
            discord.SelectOption(label='Moderation', value="Mod", emoji='<:Astra_moderation:1141303878541918250>'),
            discord.SelectOption(label='Automod', value="Automod", emoji="<:Astra_time:1141303932061233202>"),
            discord.SelectOption(label='Backup', value="backups", emoji='<:Astra_file1:1141303837181886494>'),
            discord.SelectOption(label='Tickets', value="Ticket", emoji='<:Astra_ticket:1141833836204937347>'),
            discord.SelectOption(label='Settings & Setup', value="Settings", emoji='<:Astra_settings:1061390649200476170>'),

            # Server Features
            discord.SelectOption(label="Levelsystem", value="Level", emoji="<:Astra_level:1141825043278598154>"),
            discord.SelectOption(label='Economy', value="Eco", emoji='<:Astra_cookie:1141303831293079633>'),
            discord.SelectOption(label='Nachrichten', value="Messages", emoji='<:Astra_messages:1141303867850641488>'),
            discord.SelectOption(label='Geburtstage', value="bdays", emoji='<:Astra_gw_closed:1141303848695238686>'),
            discord.SelectOption(label="Giveaways", value="GW", emoji="<:Astra_gw1:1141303852889550928>"),
            discord.SelectOption(label='Information', value="Info", emoji='<:Astra_support:1141303923752325210>'),

            # Unterhaltung
            discord.SelectOption(label='Fun', value="Fun", emoji='<:Astra_fun:1141303841665601667>'),
            discord.SelectOption(label='Minispiele', value="Minigames", emoji='<:Astra_minigames:1141303876528648232>'),
        ]
        # WICHTIG: custom_id setzen + timeoutlose View (siehe HelpView) macht das Select persistent
        super().__init__(
            placeholder='Wähle eine Seite',
            min_values=1,
            max_values=1,
            options=options,
            custom_id="help:dropdown"  # <- stabiler, eindeutiger Identifier
        )

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("HelpCog")
        description2 = cog.pages.get(self.values[0], "Seite nicht gefunden!")
        embed = discord.Embed(
            title=" ",
            description=description2,
            colour=discord.Colour.blue()
        )
        embed.set_author(
            name=f"Command Menü | {self.values[0]}",
            icon_url=getattr(interaction.client.user.display_avatar, "url", None)
        )
        guild_icon_url = getattr(getattr(interaction.guild, "icon", None), "url", None)
        embed.set_footer(text="Astra Development ©2025", icon_url=guild_icon_url)

        # Für Folge-Interaktionen wieder dieselbe persistent View-Klasse verwenden
        view = HelpView(cog)
        await interaction.response.edit_message(embed=embed, view=view)


class HelpView(View):
    """Persistent Help-View. Muss mit bot.add_view(...) registriert werden (siehe on_ready)."""
    def __init__(self, cog: commands.Cog):
        # timeout=None => persistent
        super().__init__(timeout=None)
        self.add_item(Dropdown(cog))
        self.add_item(WebsiteButton())


class HelpCog(commands.Cog):
    # Aliasse für abweichende Gruppen-Namen
    ALIASES = {
        # englisch -> tatsächlich genutzter Name
        "economy": "eco",
        "job": "job",
        # hier ggf. weitere Synonyme hinterlegen
        "levels": "levelsystem",
        "level": "levelsystem",
        "levelsystem": "levelsystem",
        "backup": "backup",
        "gewinnspiele": "gewinnspiel",
        "gewinnspiel": "gewinnspiel",
        "benachrichtigungen": "benachrichtigung",
        "notifications": "benachrichtigung",
        "info": "info",
        "infos": "info",
        "erinnerung": "erinnerung",
    }

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.uptime = datetime.utcnow()
        self.command_ids: dict[str, int] = {}           # "key" -> command id
        self.command_descriptions: dict[str, str] = {}  # "key" -> description
        self.pages: dict[str, str] = {}
        self._view_registered = False  # verhindert doppeltes Registrieren bei Reconnects

    async def cog_load(self):
        self._build_pages()

    async def on_ready_cache_ids(self):
        """Cacht IDs (für Slash-Mentions) und Beschreibungen inkl. aller Subcommands – direkt aus der API-Struktur."""
        await self.bot.wait_until_ready()
        self.command_ids.clear()
        self.command_descriptions.clear()

        def walk_api(prefix: str, node: dict, top_id: int):
            # node: {"name":..., "description":..., "type":..., "options":[...]}
            name = node.get("name", "")
            full_key = (f"{prefix} {name}".strip()).lower()
            desc = (node.get("description") or "").strip()
            if full_key:
                self.command_ids[full_key] = top_id
                self.command_descriptions[full_key] = desc
            # Rekursiv für Subcommand(-groups)
            for opt in (node.get("options") or []):
                if opt.get("type") in (1, 2):  # 1=SUB_COMMAND, 2=SUB_COMMAND_GROUP
                    walk_api(full_key, opt, top_id)

        cmds = await self.bot.tree.fetch_commands()
        for cmd in cmds:
            data = cmd.to_dict()
            top_id = cmd.id
            # Top-Level Command selbst
            top_key = data["name"].lower()
            self.command_ids[top_key] = top_id
            self.command_descriptions[top_key] = (data.get("description") or "").strip()
            # Kinder (Subcommands/-groups) rekursiv verarbeiten
            for opt in (data.get("options") or []):
                if opt.get("type") in (1, 2):
                    walk_api(top_key, opt, top_id)

        # Aliasse (IDs spiegeln, Descriptions werden per _resolve_alias gefunden)
        for alias, real in self.ALIASES.items():
            if real in self.command_ids and alias not in self.command_ids:
                self.command_ids[alias] = self.command_ids[real]

    def _normalize_key(self, path: str) -> str:
        return path.strip().lower()

    def _resolve_alias(self, key: str) -> str:
        """Wendet Alias nur auf das erste Wort (Group) an, respektiert Subcommands."""
        if " " in key:
            head, tail = key.split(" ", 1)
            return f"{self.ALIASES.get(head, head)} {tail}".lower()
        return self.ALIASES.get(key, key).lower()

    def _cid(self, path: str) -> int:
        """
        Holt robust die Command-ID für Slash-Mentions.
        Für Subcommands wird weiterhin die Gruppen-ID verwendet.
        """
        key = self._normalize_key(path)
        key = self._resolve_alias(key)

        if key in self.command_ids:
            return self.command_ids[key]

        if " " in key:
            group = key.split(" ", 1)[0]
            for k in self.command_ids.keys():
                if k == group or k.startswith(group + " "):
                    return self.command_ids[k]

        for k in self.command_ids.keys():
            if k == key or k.startswith(key + " ") or key.startswith(k + " "):
                return self.command_ids[k]

        return 0

    def _cdesc(self, path: str) -> str:
        """
        Liefert die automatisch gecachte Beschreibung.
        Bevorzugt Subcommand-Description bei 'group sub'.
        """
        key = self._normalize_key(path)
        key = self._resolve_alias(key)

        if key in self.command_descriptions and self.command_descriptions[key]:
            return self.command_descriptions[key]

        if " " in key:
            group = key.split(" ", 1)[0]
            if group in self.command_descriptions and self.command_descriptions[group]:
                return self.command_descriptions[group]

        for k, v in self.command_descriptions.items():
            if (k == key or k.startswith(key + " ") or key.startswith(k + " ")) and v:
                return v

        return "Keine Beschreibung vorhanden."

    def _usage(self, name: str, options: list | None) -> str:
        if not options:
            return f"/{name}"

        args = []
        for o in options:
            if o["type"] in (1, 2):
                continue
            arg = f"<{o['name']}>" if o.get("required") else f"[{o['name']}]"
            args.append(arg)

        return f"/{name} " + " ".join(args)

    def _walk(self, data: dict, prefix=""):
        out = []
        name = f"{prefix} {data['name']}".strip()

        out.append({
            "name": name,
            "description": data.get("description") or "Keine Beschreibung",
            "options": data.get("options", [])
        })

        for o in data.get("options", []):
            if o["type"] in (1, 2):
                out.extend(self._walk(o, name))

        return out

    @staticmethod
    def split_text(text: str, limit: int = 3500):
        parts = []
        current = ""

        for line in text.splitlines(keepends=True):
            if len(current) + len(line) > limit:
                parts.append(current)
                current = ""
            current += line

        if current:
            parts.append(current)

        return parts

    async def send_all_commands(self, channel: discord.TextChannel):
        cmds = await self.bot.tree.fetch_commands()
        text = ""

        for cmd in cmds:
            for c in self._walk(cmd.to_dict()):
                usage = self._usage(c["name"], c["options"])
                text += (
                    f"**/{c['name']}**\n"
                    f"> {c['description']}\n"
                    f"`{usage}`\n\n"
                )

        for i, part in enumerate(self.split_text(text)):
            embed = discord.Embed(
                title="📘 Alle Commands" if i == 0 else None,
                description=part,
                colour=discord.Colour.blue()
            )
            embed.set_footer(text=f"Astra Development ©2026 • Seite {i + 1}")
            await channel.send(embed=embed)


    @commands.Cog.listener()
    async def on_ready(self):
        await self.on_ready_cache_ids()
        self._build_pages()
        # PERSISTENTE VIEW REGISTRIEREN (nur einmal)
        if not self._view_registered:
            # Ohne message_id registrieren => reagiert auf alle Komponenten mit passender custom_id
            self.bot.add_view(HelpView(self))
            self._view_registered = True

    def _build_pages(self):
        self.pages = {
            "Mod": f"> <:Astra_support:1141303923752325210> Nutze diese Befehle, um deinen Server sauber und sicher zu halten. Kicke, banne oder lösche Nachrichten schnell.\n\n> **👥 × User Befehle:**\n> Keine User Befehle.\n\n> **👮‍♂ × Team Befehle:**\n> </kick:{self._cid('kick')}> - {self._cdesc('kick')}\n> </ban:{self._cid('ban')}> - {self._cdesc('ban')}\n> </unban:{self._cid('unban')}> - {self._cdesc('unban')}\n> </banlist:{self._cid('banlist')}> - {self._cdesc('banlist')}\n> </clear:{self._cid('clear')}> - {self._cdesc('clear')}",
            "Level": f"> <:Astra_support:1141303923752325210> Verwalte das Levelsystem, belohne Aktivität und motiviere deine Community. Perfekt für Rankings und Events.\n\n> **👥 × User Befehle:**\n> </levelsystem rank:{self._cid('levelsystem')}> - {self._cdesc('levelsystem rank')}\n> </levelsystem leaderboard:{self._cid('levelsystem')}> - {self._cdesc('levelsystem leaderboard')}\n\n> **👮‍♂ × Team Befehle:**\n> </levelsystem status:{self._cid('levelsystem')}> - {self._cdesc('levelsystem status')}\n> </levelsystem config:{self._cid('levelsystem')}> - {self._cdesc('levelsystem config')}\n> </setlevel:{self._cid('setlevel')}> - {self._cdesc('setlevel')}\n> </setxp:{self._cid('setxp')}> - {self._cdesc('setxp')}",
            "GW": f"> <:Astra_support:1141303923752325210> Organisiere Gewinnspiele und steigere die Aktivität deiner Community. Einfach starten und verwalten.\n\n> **👥 × User Befehle:**\n> Keine User Befehle.\n\n> **👮‍♂ × Team Befehle:**\n> </gewinnspiel starten:{self._cid('gewinnspiel')}> - {self._cdesc('gewinnspiel starten')}\n> </gewinnspiel verwalten:{self._cid('gewinnspiel')}> - {self._cdesc('gewinnspiel verwalten')}",
            "Settings": f"> <:Astra_support:1141303923752325210> Passe den Server individuell an. Erstelle Rollen, richte AFK, Erinnerungen oder Reactionroles ein.\n\n> **👥 × User Befehle:**\n> </afk:{self._cid('afk')}> - {self._cdesc('afk')}\n> </erinnerungen:{self._cid('erinnerungen')}> - {self._cdesc('erinnerungen')}\n\n> **👮‍♂ × Team Befehle:**\n> </autorole:{self._cid('autorole')}> - {self._cdesc('autorole')}\n> </voicesetup:{self._cid('voicesetup')}> - {self._cdesc('voicesetup')}\n> </reactionrole erstellen:{self._cid('reactionrole')}> - {self._cdesc('reactionrole erstellen')}\n> </reactionrole anzeigen:{self._cid('reactionrole')}> - {self._cdesc('reactionrole anzeigen')}",
            "Ticket": f"> <:Astra_support:1141303923752325210> Biete schnellen Support mit einem Ticketsystem. Einfach Tickets erstellen, verwalten und dokumentieren.\n\n> **👥 × User Befehle:**\n> Keine User Befehle.\n\n> **👮‍♂ × Team Befehle:**\n> </ticket setup:{self._cid('ticket')}> - {self._cdesc('ticket setup')}\n> </ticket löschen:{self._cid('ticket')}> - {self._cdesc('ticket löschen')}\n> </ticket anzeigen:{self._cid('ticket')}> - {self._cdesc('ticket anzeigen')}\n> </ticket log:{self._cid('ticket')}> - {self._cdesc('ticket log')}",
            "Automod": f"> <:Astra_support:1141303923752325210> Automatisiere Moderation mit Filtern und Logs. Schütze deinen Server effektiv vor Regelverstößen.\n\n> **👥 × User Befehle:**\n> Keine User Befehle.\n\n> **👮‍♂ × Team Befehle:**\n> </warn:{self._cid('warn')}> - {self._cdesc('warn')}\n> </unwarn:{self._cid('unwarn')}> - {self._cdesc('unwarn')}\n> </warns:{self._cid('warns')}> - {self._cdesc('warns')}\n> </automod setup:{self._cid('automod')}> - {self._cdesc('automod setup')}\n> </automod config:{self._cid('automod')}> - {self._cdesc('automod config')}\n> </automod reset:{self._cid('automod')}> - {self._cdesc('automod reset')}\n> </modlog:{self._cid('modlog')}> - {self._cdesc('modlog')}",
            "Info": f"> <:Astra_support:1141303923752325210> Erhalte nützliche Infos zu Usern, Server oder dem Bot. Alles Wichtige schnell abrufbar.\n\n> **👥 × User Befehle:**\n> </help:{self._cid('help')}> - {self._cdesc('help')}\n> </about:{self._cid('about')}> - {self._cdesc('about')}\n> </invite:{self._cid('invite')}> - {self._cdesc('invite')}\n> </support:{self._cid('support')}> - {self._cdesc('support')}\n> </ping:{self._cid('ping')}> - {self._cdesc('ping')}\n> </uptime:{self._cid('uptime')}> - {self._cdesc('uptime')}\n> </info kanal:{self._cid('info')}> - {self._cdesc('info kanal')}\n> </info server:{self._cid('info')}> - {self._cdesc('info server')}\n> </info rolle:{self._cid('info')}> - {self._cdesc('info rolle')}\n> </info user:{self._cid('info')}> - {self._cdesc('info user')}\n> </info wetter:{self._cid('info')}> - {self._cdesc('info wetter')}\n> </statistik server:{self._cid('statistik')}> - {self._cdesc('statistik server')}\n> </statistik user:{self._cid('statistik')}> - {self._cdesc('statistik user')}\n> </statistik reset:{self._cid('statistik')}> - {self._cdesc('statistik reset')}\n\n> **👮‍♂ × Team Befehle:**\n> Keine Team Befehle.",
            "Fun": f"> <:Astra_support:1141303923752325210> Bringe Spaß in den Chat mit Filtern, Memes und mehr. Ideal für lockere Unterhaltung.\n\n> **👥 × User Befehle:**\n> </wanted:{self._cid('wanted')}> - {self._cdesc('wanted')}\n> </pix:{self._cid('pix')}> - {self._cdesc('pix')}\n> </wasted:{self._cid('wasted')}> - {self._cdesc('wasted')}\n> </triggered:{self._cid('triggered')}> - {self._cdesc('triggered')}\n> </gay:{self._cid('gay')}> - {self._cdesc('gay')}\n> </color:{self._cid('color')}> - {self._cdesc('color')}\n> </meme:{self._cid('meme')}> - {self._cdesc('meme')}\n> </qrcode:{self._cid('qrcode')}> - {self._cdesc('qrcode')}\n\n> **👮‍♂ × Team Befehle:**\n> Keine Team Befehle.",
            "Eco": f"> <:Astra_support:1141303923752325210> Verdiene und verwalte virtuelles Geld. Spiele, arbeite oder handle mit anderen Usern.\n\n> **👥 × User Befehle:**\n> </eco balance:{self._cid('economy')}> - {self._cdesc('economy balance')}\n> </eco deposit:{self._cid('economy')}> - {self._cdesc('economy deposit')}\n> </eco withdraw:{self._cid('economy')}> - {self._cdesc('economy withdraw')}\n> </eco leaderboard:{self._cid('economy')}> - {self._cdesc('economy leaderboard')}\n> </eco beg:{self._cid('economy')}> - {self._cdesc('economy beg')}\n> </eco rob:{self._cid('economy')}> - {self._cdesc('economy rob')}\n> </eco rps:{self._cid('economy')}> - {self._cdesc('economy rps')}\n> </eco slot:{self._cid('economy')}> - {self._cdesc('economy slot')}\n> </eco coinflip:{self._cid('economy')}> - {self._cdesc('economy coinflip')}\n> </eco blackjack:{self._cid('economy')}> - {self._cdesc('economy blackjack')}\n> </job list:{self._cid('job')}> - {self._cdesc('job list')}\n> </job apply:{self._cid('job')}> - {self._cdesc('job apply')}\n> </job quit:{self._cid('job')}> - {self._cdesc('job quit')}\n> </job work:{self._cid('job')}> - {self._cdesc('job work')}\n\n> **👮‍♂ × Team Befehle:**\n> Keine Team Befehle.",
            "Messages": f"> <:Astra_support:1141303923752325210> Verwalte Willkommens-, Abschieds- und Youtube/Twitch Benachrichtigungen.\n\n> **👥 × User Befehle:**\n> </joinmsg:{self._cid('joinmsg')}> - {self._cdesc('joinmsg')}\n> </leavemsg:{self._cid('leavemsg')}> - {self._cdesc('leavemsg')}\n> </autoreact:{self._cid('autoreact')}> - {self._cdesc('autoreact')}\n> </embedfy:{self._cid('embedfy')}> - {self._cdesc('embedfy')}\n\n> **👮‍♂ × Team Befehle:**\n> </benachrichtigung youtube:{self._cid('benachrichtigung')}> - {self._cdesc('benachrichtigung youtube')}\n> </benachrichtigung twitch:{self._cid('benachrichtigung')}> - {self._cdesc('benachrichtigung twitch')}\n> </benachrichtigung info:{self._cid('benachrichtigung')}> - {self._cdesc('benachrichtigung info')}",
            "bdays": f"> <:Astra_calender:1141303828625489940> Automatische Geburtstagsgrüße – Astra erinnert an Geburtstage auf deinem Server und sendet Glückwünsche pünktlich zur gewünschten Uhrzeit.\n\n> **👥 × User Befehle:**\n> </geburtstag setzen:{self._cid('geburtstag')}> - {self._cdesc('geburtstag setzen')}\n> </geburtstag anzeigen:{self._cid('geburtstag')}> - {self._cdesc('geburtstag anzeigen')}\n> </geburtstag löschen:{self._cid('geburtstag')}> - {self._cdesc('geburtstag löschen')}\n\n> **👮‍♂ × Team Befehle:**\n> </geburtstag setup:{self._cid('geburtstag')}> - {self._cdesc('geburtstag setup')}\n> </geburtstag nachricht:{self._cid('geburtstag')}> - {self._cdesc('geburtstag nachricht')}\n> </geburtstag status:{self._cid('geburtstag')}> - {self._cdesc('geburtstag status')}",
            "Minigames": f"> <:Astra_support:1141303923752325210> Spiele direkt im Chat und fordere dich oder andere heraus.\n\n> **👥 × User Befehle:**\n> </hangman:{self._cid('hangman')}> - {self._cdesc('hangman')}\n> </snake start:{self._cid('snake')}> - {self._cdesc('snake start')}\n> </snake highscore:{self._cid('snake')}> - {self._cdesc('snake highscore')}\n\n> **👮‍♂ × Team Befehle:**\n> </emojiquiz:{self._cid('emojiquiz')}> - {self._cdesc('emojiquiz')}\n> </guessthenumber:{self._cid('guessthenumber')}> - {self._cdesc('guessthenumber')}\n> </counting:{self._cid('counting')}> - {self._cdesc('counting')}",
            "backups": f"> <:Astra_support:1141303923752325210> Sichere deinen Server mit einem Klick – Backups erstellen, wiederherstellen oder rückgängig machen. Immer sicher, immer unter Kontrolle.\n\n> **👥 × User Befehle:**\n> Keine User Befehle.\n\n> **👮‍♂ × Team Befehle:**\n> </backup erstellen:{self._cid('backup erstellen')}> - {self._cdesc('backup erstellen')}\n> </backup laden:{self._cid('backup laden')}> - {self._cdesc('backup laden')}\n> </backup zurücksetzen:{self._cid('backup zurücksetzen')}> - {self._cdesc('backup zurücksetzen')}\n> </backup status:{self._cid('backup status')}> - {self._cdesc('backup status')}\n> </backup löschen:{self._cid('backup löschen')}> - {self._cdesc('backup löschen')}\n> </backup liste:{self._cid('backup liste')}> - {self._cdesc('backup liste')}\n> </backup exportieren:{self._cid('backup exportieren')}> - {self._cdesc('backup exportieren')}\n> </backup importieren:{self._cid('backup importieren')}> - {self._cdesc('backup importieren')}",
        }

    @app_commands.command(name="help", description="Zeigt dir eine Liste aller Befehle an.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def help(self, interaction: discord.Interaction):
        view = View(timeout=None)
        view.add_item(Dropdown(self))  # <-- hier war der Fehler
        view.add_item(WebsiteButton())

        delta_uptime = datetime.utcnow() - self.uptime
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        embed = discord.Embed(
            colour=discord.Colour.blue(),
            title="Help Menü",
            description=(
                "<:Astra_info:1141303860556738620> **Wichtige Informationen**\n"
                "Hier findest du alle Commands.\n"
                "Falls du Hilfe brauchst, komm auf unseren [Support Server ➚](https://astra-bot.de/support).\n\n"
                f"**Uptime:** {days}d {hours}h {minutes}m {seconds}s\n"
                f"**Ping:** {self.bot.latency * 1000:.0f} ms\n\n"
            )
        )

        embed.add_field(
            name="Über Astra",
            value=(
                "> <:Astra_support:1141303923752325210> Astra ist ein leistungsstarker Discord-Bot für **Moderation und Sicherheit**. "
                "Mit Automod, Logs und **Server-Backups** behältst du jederzeit die Kontrolle – "
                "ergänzt durch Levelsystem, Tickets, Economy, Minigames und mehr.\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="`⚡` Quick Actions (NEU!)",
            value=(
                "> Du kannst Moderation direkt per Rechtsklick nutzen:\n"
                "> <:Astra_punkt:1141303896745201696> Rechtsklick auf User → **Apps → Warn**\n"
                "> <:Astra_punkt:1141303896745201696> Kein Command nötig\n"
                "> <:Astra_punkt:1141303896745201696> Schneller Workflow\n"
                "> `🔥` Besonders praktisch für Moderatoren"
            ),
            inline=False
        )

        embed.add_field(
            name="Letzte Updates",
            value=(
                "> <:Astra_punkt:1141303896745201696> Levelsystem (UI, XP, Struktur)\n"
                "> <:Astra_punkt:1141303896745201696> Help-System überarbeitet\n"
                "> <:Astra_punkt:1141303896745201696> Reminder-System (UI + Tasks)\n"
                "> <:Astra_punkt:1141303896745201696> AFK-System verbessert\n"
                "> <:Astra_punkt:1141303896745201696> Backend & Logging optimiert"
            ),
            inline=False,
        )

        embed.add_field(
            name="Links",
            value=(
                "[Einladen](https://astra-bot.de/invite)"
                " | [Support](https://astra-bot.de/support)"
                " | [Voten](https://top.gg/bot/1113403511045107773/vote)"
            ),
            inline=False
        )

        # safer: avatar/icon können None sein
        author_icon = getattr(interaction.client.user.display_avatar, "url", None)
        embed.set_author(name="Astra – Hilfe", icon_url=author_icon)

        guild_icon_url = getattr(getattr(interaction.guild, "icon", None), "url", None)
        embed.set_footer(text="Astra Development ©2025", icon_url=guild_icon_url)

        # Banner: Entweder absolute URL ODER als Attachment senden (siehe unten)
        embed.set_image(url="https://cdn.discordapp.com/attachments/1141116983358804118/1404850199507243171/Neuer-Astra-Banner-animiert.gif?ex=689cb034&is=689b5eb4&hm=94f6a826f88983e0b39d61449182aa5bad616d02850c34d55fca4d57433274ca&")

        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))