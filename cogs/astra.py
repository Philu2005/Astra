import discord
import psutil
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from psutil import Process, virtual_memory
from dotenv import load_dotenv
import os
import time
import matplotlib.pyplot as plt
import matplotlib.ticker as tkr
import matplotlib.font_manager as fm
import numpy as np
from matplotlib import patheffects
import platform
import io
from PIL import Image
import asyncio
import tempfile
from discord import ui
from wcwidth import wcswidth
import aiohttp

async def get_best_join_channel(guild: discord.Guild) -> discord.TextChannel | None:
    me = guild.me
    if not me:
        return None

    # 1️⃣ System Channel (wenn sendbar)
    ch = guild.system_channel
    if ch and ch.permissions_for(me).send_messages:
        return ch

    # 2️⃣ Bevorzugte Kanalnamen
    preferred = (
        "general", "allgemein", "chat", "welcome",
        "start", "server", "hauptchat"
    )

    for name in preferred:
        for ch in guild.text_channels:
            if name in ch.name.lower() and ch.permissions_for(me).send_messages:
                return ch

    # 3️⃣ Erster Textkanal mit Send-Rechten
    for ch in guild.text_channels:
        perms = ch.permissions_for(me)
        if perms.send_messages and perms.view_channel:
            return ch

    return None

# ------------------------------------------------------------
#  CPU & RAM Helpers
# ------------------------------------------------------------
def get_cpu_usage() -> float:
    # 1‑Sekunden‑Messung => realistische Schwankungen
    return psutil.cpu_percent(interval=1)


def get_ram_usage() -> float:
    return psutil.virtual_memory().percent


# ------------------------------------------------------------
#  Graph Generator (Dark‑Dashboard‑Style, verbessert)
# ------------------------------------------------------------
def generate_graph(cpu, ram, t):
    # 1)  Font registrieren
    FONT_PATH = "cogs/fonts/Poppins-SemiBold.ttf"  # dein absoluter oder relativer Pfad
    fm.fontManager.addfont(FONT_PATH)  # <‑ in den Matplotlib‑Cache eintragen
    # fm._rebuild()  # Font‑Datenbank neu aufbauen

    # Interner Name exakt auslesen
    POPPINS_NAME = fm.FontProperties(fname=FONT_PATH).get_name()
    # -> gibt meist "Poppins SemiBold" zurück

    # ---------- Farben ----------
    BG_FIG = "#181818"     # super‑dunkel
    BG_AX  = "#222222"     # etwas heller
    CPU_C  = "#36A8FF"     # Astra‑Blau
    RAM_C  = "#FFB547"     # Amber‑Orange

    # ---------- Interpolation (smooth) ----------
    x  = np.array(t)
    xs = np.linspace(x.min(), x.max(), 240)
    cpu_s = np.interp(xs, x, cpu)
    ram_s = np.interp(xs, x, ram)

    # ---------- Global Style ----------
    plt.rcParams.update({
        "font.family": POPPINS_NAME,  # Alternativ: 'Segoe UI', 'Ubuntu', 'DejaVu Sans'
        "font.size":   10,
        "axes.edgecolor": "white",
        "axes.labelcolor": "white",
        "xtick.color": "white",
        "ytick.color": "white",
        "text.color":  "white",
        "figure.autolayout": True,
    })

    fig, ax1 = plt.subplots(figsize=(11, 5.5), dpi=130)
    fig.patch.set_facecolor(BG_FIG)
    ax1.set_facecolor(BG_AX)

    # ---------- Optional: Padding für Platz auf Achsen ----------
    fig.subplots_adjust(left=0.08, right=0.92)

    # ---------- CPU‑Linie ----------
    cpu_line, = ax1.plot(
        xs, cpu_s, color=CPU_C, lw=2.4, label="CPU",
        path_effects=[patheffects.Stroke(linewidth=3.4, foreground="#0E4066"),
                      patheffects.Normal()]
    )
    ax1.fill_between(xs, cpu_s, color=CPU_C, alpha=0.12)

    ax1.set_ylabel("CPU (%)", color=CPU_C, weight="bold")
    ax1.tick_params(axis="y", labelcolor=CPU_C)
    ax1.set_ylim(0, max(10, max(cpu) + 5))

    # ---------- RAM‑Linie (rechte Y‑Achse) ----------
    ax2 = ax1.twinx()
    ram_line, = ax2.plot(
        xs, ram_s, color=RAM_C, lw=2.4, label="RAM",
        path_effects=[patheffects.Stroke(linewidth=3.4, foreground="#664315"),
                      patheffects.Normal()]
    )
    ax2.fill_between(xs, ram_s, color=RAM_C, alpha=0.07)  # << dunkleres RAM-Fill

    ax2.set_ylabel("RAM (%)", color=RAM_C, weight="bold")
    ax2.tick_params(axis="y", labelcolor=RAM_C)
    ax2.set_ylim(min(0, min(ram) - 5), min(100, max(ram) + 5))

    # ---------- Achsen & Grid ----------
    ax1.set_xlabel("Zeit (Sekunden)")
    ax1.set_title("Systemauslastung – CPU & RAM", fontsize=16, weight="bold", pad=10)
    ax1.xaxis.set_major_locator(tkr.MaxNLocator(integer=True))
    ax1.grid(ls="--", lw=0.6, alpha=0.15, color="white")  # << smoother Grid

    # ---------- Legende ----------
    ax1.legend(
        handles=[cpu_line, ram_line],
        labels=["CPU", "RAM"],
        loc="upper left",
        frameon=False,
        fontsize=9
    )

    # ---------- Punkt‑Labels ----------
    for x_pt, y_pt in zip(x, cpu):
        ax1.text(x_pt, y_pt + 0.3, f"{y_pt:.1f}", color=CPU_C, fontsize=8, ha="center")
    for x_pt, y_pt in zip(x, ram):
        ax2.text(x_pt, y_pt + 0.3, f"{y_pt:.1f}", color=RAM_C, fontsize=8, ha="center")

    # ---------- Export ----------
    save_path = "system_usage_graph.png"
    plt.savefig(save_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return save_path


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





class testbutton(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label='testbutton', style=discord.ButtonStyle.green)
    async def testbutton(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Confirming', ephemeral=True)


class astra(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.uptime = datetime.utcnow()
        self.session = aiohttp.ClientSession()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    embed = discord.Embed(
                        title="✨ Danke fürs Einladen von Astra!",
                        description=(
                            "Astra ist ein moderner Discord-Bot für **Administration, Moderation und Support**.\n"
                            "Alle Systeme sind **optional**, **server-spezifisch** und lassen sich flexibel konfigurieren."
                        ),
                        colour=discord.Colour.blurple()
                    )

                    embed.add_field(
                        name="🧩 Wichtige Module",
                        value=(
                            "• Moderation & Automod\n"
                            "• Tickets & Support-System\n"
                            "• Tempchannels & Reaction Roles\n"
                            "• Levelsystem, Utilities & mehr"
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="🚀 Schnellstart",
                        value=(
                            "• `/help` – Übersicht aller Funktionen\n"
                            "• `/ticket setup` – Support-System einrichten\n"
                            "• `/automod` – Automoderation konfigurieren"
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="🔗 Wichtige Links",
                        value=(
                            "**[Website](https://astra-bot.de/)**\n"
                            "**[Support-Server](https://astra-bot.de/support)**\n"
                            "**[Astra einladen](https://astra-bot.de/invite)**"
                        ),
                        inline=False
                    )

                    embed.set_footer(
                        text="Astra • Klar • Modular • Server-fokussiert",
                        icon_url=self.bot.user.display_avatar.url
                    )

                    embed.set_author(
                        name="Astra",
                        icon_url=self.bot.user.display_avatar.url
                    )

                    try:
                        await guild.owner.send(embed=embed)
                    except discord.Forbidden:
                        pass
                    try:
                        guilds = self.bot.get_guild(1141116981697859736)
                        channels = guilds.get_channel(1141116983815962821)
                        embed = discord.Embed(colour=discord.Colour.green(), title=f"Neuer server! ({len(self.bot.guilds)})",
                                              description="Hier sind einige Informationen:")
                        embed.add_field(name="Name", value=f"{guild.name}", inline=True)
                        embed.add_field(name="ID", value=f"{guild.id}", inline=True)
                        embed.add_field(name="Erstellt am", value=f"{guild.created_at.__format__('at the %d.%m.%Y around %X')}",
                                        inline=False)
                        embed.add_field(name="User count", value=f"{guild.member_count}", inline=False)
                        embed.add_field(name="Owner", value=f"{guild.owner}", inline=False)
                        embed.set_thumbnail(url=guild.icon)
                        await channels.send(embed=embed)
                    except:
                        pass
                    servers = len(self.bot.guilds)
                    users = len(self.bot.users)
                    commands = len(self.bot.tree.get_commands())
                    channel = await get_best_join_channel(guild)
                    if not channel:
                        return

                    embed = discord.Embed(
                        colour=discord.Colour.blurple(),
                        title="✨ ASTRA ✨",
                        description=(
                            "Hallo! Ich bin **Astra** – ein modularer Discord-Bot für "
                            "Moderation, Organisation und Community-Features.\n\n"
                            "Alle Systeme sind **optional**, **server-spezifisch** "
                            "und lassen sich individuell konfigurieren."
                        )
                    )

                    embed.add_field(
                        name="🚀 Schnellstart",
                        value=(
                            "• `/help` – Alle Befehle & Kategorien\n"
                            "• `/ticket setup` – Support-System einrichten\n"
                            "• `/automod` – Automoderation konfigurieren"
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="🧩 Module (Auswahl)",
                        value=(
                            "Moderation • Tickets • Levelsystem\n"
                            "Reaction Roles • Giveaways • Economy\n"
                            "Willkommen & Benachrichtigungen"
                        ),
                        inline=False
                    )

                    embed.add_field(
                        name="🔗 Links",
                        value=(
                            "**[Support-Server](https://astra-bot.de/support)**\n"
                            "**[Astra einladen](https://astra-bot.de/invite)**\n"
                            "**[Website](https://astra-bot.de/)**"
                        ),
                        inline=False
                    )

                    embed.set_footer(
                        text="Astra • Klar • Modular • Server-fokussiert",
                        icon_url=self.bot.user.display_avatar.url
                    )

                    embed.set_author(
                        name="Danke fürs Einladen!",
                        icon_url="https://cdn.discordapp.com/emojis/823981604752982077.gif"
                    )

                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        try:
            guilds = self.bot.get_guild(1141116981697859736)
            channels = guilds.get_channel(1141116983815962821)
            embed = discord.Embed(colour=discord.Colour.red(), title=f"Server verlassen! ({len(self.bot.guilds)})",
                                  description="Hier sind einige Informationen:")
            embed.add_field(name="Name", value=f"{guild.name}", inline=True)
            embed.add_field(name="ID", value=f"{guild.id}", inline=True)
            embed.add_field(name="Erstellt am", value=f"{guild.created_at.__format__('at the %d.%m.%Y around %X')}",
                            inline=False)
            embed.add_field(name="User count", value=f"{guild.member_count}", inline=False)
            embed.add_field(name="Owner", value=f"{guild.owner}", inline=False)
            embed.set_thumbnail(url=guild.icon)
            await channels.send(embed=embed)
            return
        except:
            pass

    @app_commands.command(name="about", description="Zeigt Informationen über den Bot.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def about(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        # -------- Daten sammeln -------------------------------------------
        cpu_data, ram_data = [], []
        for _ in range(10):
            cpu_data.append(get_cpu_usage())
            ram_data.append(get_ram_usage())

        time_points = list(range(10))
        graph_path = generate_graph(cpu_data, ram_data, time_points)
        graph_file = discord.File(graph_path, filename="graph.png")

        # -------- Bot‑Infos ----------------------------------------------
        bot_owner = self.bot.get_user(789555434201677824)  # <‑ deine ID
        servers = len(self.bot.guilds)
        members_total = sum(g.member_count or 0 for g in self.bot.guilds)
        members_avg = members_total / servers if servers else 0

        # -------- Uptime --------------------------------------------------
        delta = datetime.utcnow() - self.uptime
        d, r = divmod(delta.total_seconds(), 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)

        embed = discord.Embed(
            title="🛰️ Astra Systemübersicht",
            description="Hier findest du aktuelle Informationen über den Bot und seine Leistung.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="👤 Bot Owner", value=bot_owner.mention if bot_owner else "Unbekannt", inline=True)
        embed.add_field(name="🌐 Server", value=f"{servers}", inline=True)
        embed.add_field(name="👥 Nutzer", value=f"{members_total}", inline=True)
        embed.add_field(name="📊 Schnitt/Server", value=f"{members_avg:.2f}", inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
        embed.add_field(name="🤖 discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="🕓 Uptime",
                        value=f"{int(d)}d {int(h)}h {int(m)}m {int(s)}s", inline=True)
        embed.add_field(name="🛠️ Slash Cmds", value=str(len(self.bot.tree.get_commands())), inline=True)
        embed.add_field(name="🏓 Latenz", value=f"{self.bot.latency * 1000:.2f} ms", inline=True)

        embed.set_image(url="attachment://graph.png")
        embed.set_footer(text="Astra • Performance‑Überblick",
                         icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        await interaction.followup.send(embed=embed, file=graph_file)
        os.remove(graph_path)

    @app_commands.command(name="invite")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def invite(self, interaction: discord.Interaction):
        """Link um Astra einzuladen."""
        embed = discord.Embed(colour=discord.Colour.blue(), title=f"Nutze Astra auch auf deinem Server!",
                              description=f"Mit klicken auf [Invite Astra](https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands) kannst du Astra auch auf deinen Server einladen.",
                              url="https://discord.com/oauth2/authorize?client_id=1113403511045107773&permissions=2255511571262711&integration_type=0&scope=bot+applications.commands")
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="support")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def support(self, interaction: discord.Interaction):
        """Link zu unserem Support Server."""
        embed = discord.Embed(colour=discord.Colour.blue(), title="Wir freuen uns dir helfen zu können!",
                              description="Hast du Fragen oder ein Problem? Wir freuen uns dir auf unserem [support server](https://astra-bot.de/support) helfen zu können.",
                              url="https://astra-bot.de/support")
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Überprüfe die Antwortzeit (Ping) zwischen dir und dem Bot.")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def ping(self, interaction: discord.Interaction):

        start = time.perf_counter()
        await interaction.response.defer()

        raw_response = (time.perf_counter() - start) * 1000
        gateway_ping = self.bot.latency * 1000

        response_ping = round(max(raw_response - gateway_ping, 0), 2)
        gateway_ping = round(gateway_ping, 2)

        # DB Ping
        db_start = time.perf_counter()
        try:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")

            db_ping = round((time.perf_counter() - db_start) * 1000, 2)

        except Exception:
            db_ping = None

        # API Ping
        api_start = time.perf_counter()
        try:
            async with self.session.get("http://127.0.0.1:5000/status") as r:
                await r.json()

            api_ping = round((time.perf_counter() - api_start) * 1000, 2)

        except Exception:
            api_ping = None

        # ---------- helpers ----------

        services = ["Gateway", "Processing", "Database", "Astra API"]
        pings = [gateway_ping, response_ping, db_ping, api_ping]

        def fmt(ms):
            if ms is None:
                return "Fehler"
            return f"{ms:.2f} ms"

        def status(ms):
            if ms is None:
                return "⚫"
            if ms < 150:
                return "🟢"
            if ms < 400:
                return "🟡"
            if ms < 800:
                return "🟠"
            return "🔴"

        SERVICE_W = 12
        LATENCY_W = 14
        STATE_W = 5

        # Header zuerst bauen (das ist die Referenzbreite)
        header = f"| {'Service':^{SERVICE_W}} | {'Latency':^{LATENCY_W}} | {'State':^{STATE_W}} |"

        table_width = len(header)

        # Linien exakt gleich breit
        line = "+" + "-" * (table_width - 2) + "+"
        top_line = line

        title = f"| {'Astra Network Monitor':^{table_width - 4}} |"

        rows = []

        for s, p in zip(services, pings):
            rows.append(
                f"| {s:^{SERVICE_W}} | {fmt(p):^{LATENCY_W}} | {status(p):^{STATE_W - 1}} |"
            )

        values = [v for v in pings if v is not None]

        if values and max(values) > 800:
            overall = "Critical"
        elif values and max(values) > 400:
            overall = "Degraded"
        elif values and max(values) > 150:
            overall = "Minor latency"
        else:
            overall = "Operational"

        rows.append(
            f"| {'Overall':^{SERVICE_W}} | {overall:^{LATENCY_W}} | {status(max(values) if values else None):^{STATE_W - 1}} |"
        )

        panel = "\n".join([
            top_line,
            title,
            line,
            header,
            line,
            *rows,
            line
        ])

        panel = f"```\n\n{panel}\n```"

        embed = discord.Embed(
            title="🏓 Astra Ping",
            description=panel,
            colour=discord.Colour.blue()
        )

        embed.set_footer(
            text=f"{self.bot.user.name} • Performance Monitor",
            icon_url=self.bot.user.display_avatar.url
        )

        await interaction.followup.send(embed=embed)
    @app_commands.command(name="uptime")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def uptime(self, interaction: discord.Interaction):
        """Zeigt wie lang Astra online ist."""
        delta_uptime = datetime.utcnow() - self.uptime
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        embed = discord.Embed(colour=discord.Colour.green())
        embed.set_author(name=f"Online seit: {days}d {hours}h {minutes}m {seconds}s",
                         icon_url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    async def cog_unload(self):
        await self.session.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(astra(bot))