import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiomysql
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import io
from datetime import datetime, timedelta
from collections import defaultdict
import re

def strip_emojis(text):
    return re.sub(r'[^\w\s•.-]', '', text)

# =========================================================
# COG
# =========================================================

class Analytics(commands.Cog):
    """
    Astra Ultra Analytics Engine v2
    Clean • Structured • Stable
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_task.start()

    # =====================================================
    # DAILY CLEANUP (older than 30 days)
    # =====================================================

    @tasks.loop(hours=24)
    async def cleanup_task(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM analytics_messages WHERE date < CURDATE() - INTERVAL 30 DAY"
                )
                await cursor.execute(
                    "DELETE FROM analytics_voice WHERE date < CURDATE() - INTERVAL 30 DAY"
                )
                await cursor.execute(
                    "DELETE FROM analytics_daily_guild WHERE date < CURDATE() - INTERVAL 30 DAY"
                )

    # =====================================================
    # MESSAGE TRACKING
    # =====================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        today = datetime.utcnow().date()

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                await cursor.execute("""
                    INSERT INTO analytics_messages
                    (guild_id, user_id, channel_id, date, count)
                    VALUES (%s,%s,%s,%s,1)
                    ON DUPLICATE KEY UPDATE count = count + 1
                """, (message.guild.id, message.author.id,
                      message.channel.id, today))

                await cursor.execute("""
                    INSERT INTO analytics_daily_guild
                    (guild_id, date, messages)
                    VALUES (%s,%s,1)
                    ON DUPLICATE KEY UPDATE messages = messages + 1
                """, (message.guild.id, today))

    # =====================================================
    # VOICE TRACKING
    # =====================================================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        now = datetime.utcnow()

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:

                # JOIN
                if not before.channel and after.channel:
                    await cursor.execute("""
                        INSERT INTO analytics_voice_sessions
                        (guild_id, user_id, joined_at)
                        VALUES (%s,%s,%s)
                        ON DUPLICATE KEY UPDATE joined_at=%s
                    """, (member.guild.id, member.id, now, now))

                # LEAVE
                if before.channel and not after.channel:
                    await cursor.execute("""
                        SELECT joined_at FROM analytics_voice_sessions
                        WHERE guild_id=%s AND user_id=%s
                    """, (member.guild.id, member.id))

                    row = await cursor.fetchone()
                    if not row:
                        return

                    joined_at = row[0]
                    minutes = int((now - joined_at).total_seconds() / 60)

                    if minutes > 0:
                        today = now.date()

                        await cursor.execute("""
                            INSERT INTO analytics_voice
                            (guild_id,user_id,date,minutes)
                            VALUES (%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE minutes = minutes + %s
                        """, (member.guild.id, member.id,
                              today, minutes, minutes))

                        await cursor.execute("""
                            INSERT INTO analytics_daily_guild
                            (guild_id,date,voice_minutes)
                            VALUES (%s,%s,%s)
                            ON DUPLICATE KEY UPDATE voice_minutes = voice_minutes + %s
                        """, (member.guild.id, today,
                              minutes, minutes))

                    await cursor.execute("""
                        DELETE FROM analytics_voice_sessions
                        WHERE guild_id=%s AND user_id=%s
                    """, (member.guild.id, member.id))

    def create_chart(self, title, dates, msg_values, voice_values):

        msg_values = np.array(msg_values, dtype=float)
        voice_values = np.array(voice_values, dtype=float)

        dates = [datetime.combine(d, datetime.min.time()) for d in dates]
        x = mdates.date2num(dates)

        # -----------------------------------
        # DARK BLUE BACKGROUND (wie Screenshot)
        # -----------------------------------
        fig, ax = plt.subplots(figsize=(10, 4.2))
        fig.patch.set_facecolor("#070b1a")
        ax.set_facecolor("#0b1224")

        msg_color = "#4cc9f0"  # CYAN
        voice_color = "#9d4edd"  # PURPLE

        max_val = max(max(msg_values), max(voice_values), 1)

        bottom_padding = max_val * 0.08
        top_padding = max_val * 0.25

        ax.set_ylim(-bottom_padding, max_val + top_padding)

        # -----------------------------------
        # SOFTER GLOW
        # -----------------------------------
        for lw, alpha in [(12, 0.04), (8, 0.06), (5, 0.1)]:
            ax.plot(x, msg_values, linewidth=lw, color=msg_color, alpha=alpha)
            ax.plot(x, voice_values, linewidth=lw, color=voice_color, alpha=alpha)

        # MAIN LINES
        ax.plot(
            x, msg_values,
            linewidth=3,
            marker="o",
            markersize=6,
            color=msg_color,
            label="Nachrichten"
        )

        ax.plot(
            x, voice_values,
            linewidth=3,
            marker="o",
            markersize=6,
            color=voice_color,
            label="Voice Minuten"
        )

        # -----------------------------------
        # SUBTLE FILL (wie Screenshot)
        # -----------------------------------
        ax.fill_between(x, msg_values, 0, color=msg_color, alpha=0.08)
        ax.fill_between(x, voice_values, 0, color=voice_color, alpha=0.08)

        # -----------------------------------
        # GRID
        # -----------------------------------
        ax.grid(color="#1b2540", linewidth=0.8, alpha=0.8)

        # -----------------------------------
        # AXIS
        # -----------------------------------
        ax.set_ylabel("Aktivität", fontsize=12, color="#e2e8f0")


        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.DayLocator())

        ax.tick_params(axis="x", colors="#e2e8f0", labelsize=11)
        ax.tick_params(axis="y", colors="#e2e8f0", labelsize=11)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontweight("medium")

        for spine in ax.spines.values():
            spine.set_visible(False)

        # -----------------------------------
        # TITLE (optional, wenn du willst)
        # -----------------------------------
        ax.set_title(strip_emojis(title), fontsize=15, weight="bold", color="#e2e8f0", pad=12)

        # -----------------------------------
        # LEGEND
        # -----------------------------------
        legend = ax.legend(
            loc="upper left",
            frameon=False,
            fontsize=10
        )

        for text in legend.get_texts():
            text.set_color("#e2e8f0")

        # -----------------------------------
        # REMOVE EXTRA SPACE
        # -----------------------------------
        fig.tight_layout()
        plt.subplots_adjust(bottom=0.22)  # <-- DAS IST DER FIX

        buffer = io.BytesIO()

        plt.savefig(
            buffer,
            format="png",
            dpi=130  # etwas niedriger = bessere Discord Darstellung
        )

        buffer.seek(0)
        plt.close()

        return buffer

    # =====================================================
    # DATA AGGREGATION
    # =====================================================

    async def fetch_server_data(self, guild_id, start_date):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:

                await cursor.execute("""
                    SELECT date, messages, voice_minutes
                    FROM analytics_daily_guild
                    WHERE guild_id=%s AND date >= %s
                """, (guild_id, start_date))

                return await cursor.fetchall()

    async def fetch_user_data(self, guild_id, user_id, start_date):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:

                await cursor.execute("""
                    SELECT date, SUM(count) as messages
                    FROM analytics_messages
                    WHERE guild_id=%s AND user_id=%s AND date >= %s
                    GROUP BY date
                """, (guild_id, user_id, start_date))
                msg_rows = await cursor.fetchall()

                await cursor.execute("""
                    SELECT date, SUM(minutes) as voice_minutes
                    FROM analytics_voice
                    WHERE guild_id=%s AND user_id=%s AND date >= %s
                    GROUP BY date
                """, (guild_id, user_id, start_date))
                voice_rows = await cursor.fetchall()

        data = defaultdict(lambda: {"messages": 0, "voice_minutes": 0})

        for r in msg_rows:
            data[r["date"]]["messages"] = r["messages"] or 0

        for r in voice_rows:
            data[r["date"]]["voice_minutes"] = r["voice_minutes"] or 0

        return [{"date": d, **v} for d, v in data.items()]

    # =====================================================
    # MAIN FUNCTION
    # =====================================================

    async def send_stats(self, interaction, mode, days, target_id=None):

        guild = interaction.guild
        start_7 = datetime.utcnow().date() - timedelta(days=6)
        start_30 = datetime.utcnow().date() - timedelta(days=29)

        # --------------------------------------------------
        # USER MODE
        # --------------------------------------------------
        if mode == "user":

            member = guild.get_member(target_id) or interaction.user

            rows_7 = await self.fetch_user_data(guild.id, member.id, start_7)
            rows_30 = await self.fetch_user_data(guild.id, member.id, start_30)

            def total(rows, key):
                return sum(r.get(key, 0) or 0 for r in rows)

            msg_7 = total(rows_7, "messages")
            msg_30 = total(rows_30, "messages")
            voice_7 = total(rows_7, "voice_minutes")
            voice_30 = total(rows_30, "voice_minutes")

            # ---- Rank Nachrichten
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute("""
                                         SELECT user_id, SUM(count) as total
                                         FROM analytics_messages
                                         WHERE guild_id = %s
                                         GROUP BY user_id
                                         ORDER BY total DESC
                                         """, (guild.id,))
                    ranking = await cursor.fetchall()

            rank_msg = next((i + 1 for i, r in enumerate(ranking)
                             if r["user_id"] == member.id), "-")

            # ---- Rank Voice
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute("""
                                         SELECT user_id, SUM(minutes) as total
                                         FROM analytics_voice
                                         WHERE guild_id = %s
                                         GROUP BY user_id
                                         ORDER BY total DESC
                                         """, (guild.id,))
                    ranking_voice = await cursor.fetchall()

            rank_voice = next((i + 1 for i, r in enumerate(ranking_voice)
                               if r["user_id"] == member.id), "-")

            embed = discord.Embed(
                title=f"📊 Statistik • {member.display_name}",
                color=0x1f6feb
            )

            embed.description = (
                f"**🗓 Zeitraum:** 7 & 30 Tage Übersicht\n"
                f"**👤 Server Rang:** Nachrichten `#{rank_msg}` • Voice `#{rank_voice}`"
            )

            embed.add_field(
                name="💬 Nachrichten",
                value=(
                    f"**7 Tage:** `{msg_7}`\n"
                    f"**30 Tage:** `{msg_30}`"
                ),
                inline=True
            )

            embed.add_field(
                name="🎙 Voice Minuten",
                value=(
                    f"**7 Tage:** `{voice_7}`\n"
                    f"**30 Tage:** `{voice_30}`"
                ),
                inline=True
            )

            # Chart (7 Tage)
            dates = [start_7 + timedelta(days=i) for i in range(7)]
            data = {r["date"]: r for r in rows_7}
            msg_values = [data.get(d, {}).get("messages", 0) for d in dates]
            voice_values = [data.get(d, {}).get("voice_minutes", 0) for d in dates]

            chart = self.create_chart(
                f"{member.display_name} • 7 Tage Performance",
                dates,
                msg_values,
                voice_values
            )

        # --------------------------------------------------
        # SERVER MODE
        # --------------------------------------------------
        # --------------------------------------------------
        # SERVER MODE
        # --------------------------------------------------
        else:

            rows_7 = await self.fetch_server_data(guild.id, start_7)
            rows_30 = await self.fetch_server_data(guild.id, start_30)

            def total(rows, key):
                return sum(r.get(key, 0) or 0 for r in rows)

            msg_7 = total(rows_7, "messages")
            msg_30 = total(rows_30, "messages")
            voice_7 = total(rows_7, "voice_minutes")
            voice_30 = total(rows_30, "voice_minutes")

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # ---- Top Channel (7 Tage)
                    await cursor.execute("""
                                         SELECT channel_id, SUM(count) as total
                                         FROM analytics_messages
                                         WHERE guild_id = %s
                                           AND date >= %s
                                         GROUP BY channel_id
                                         ORDER BY total DESC
                                         LIMIT 1
                                         """, (guild.id, start_7))
                    top_channel = await cursor.fetchone()

                    # ---- Top 3 User (Nachrichten)
                    await cursor.execute("""
                                         SELECT user_id, SUM(count) as total
                                         FROM analytics_messages
                                         WHERE guild_id = %s
                                           AND date >= %s
                                         GROUP BY user_id
                                         ORDER BY total DESC
                                         LIMIT 3
                                         """, (guild.id, start_7))
                    top_users_msg = await cursor.fetchall()

                    # ---- Top 3 Voice User
                    await cursor.execute("""
                                         SELECT user_id, SUM(minutes) as total
                                         FROM analytics_voice
                                         WHERE guild_id = %s
                                           AND date >= %s
                                         GROUP BY user_id
                                         ORDER BY total DESC
                                         LIMIT 3
                                         """, (guild.id, start_7))
                    top_users_voice = await cursor.fetchall()

            # Format Top Channel
            if top_channel:
                channel = guild.get_channel(top_channel["channel_id"])
                top_channel_text = f"{channel.mention} • {top_channel['total']} Nachrichten"
            else:
                top_channel_text = "Keine Aktivität"

            # Format Top User Nachrichten
            if top_users_msg:
                ranking_text = ""
                for i, row in enumerate(top_users_msg, 1):
                    member = guild.get_member(row["user_id"])
                    if member:
                        ranking_text += f"`{i}.` {member.mention} • {row['total']}\n"
            else:
                ranking_text = "Keine Daten"

            # Format Top Voice User
            if top_users_voice:
                voice_ranking_text = ""
                for i, row in enumerate(top_users_voice, 1):
                    member = guild.get_member(row["user_id"])
                    if member:
                        voice_ranking_text += f"`{i}.` {member.mention} • {row['total']} Min\n"
            else:
                voice_ranking_text = "Keine Daten"

            embed = discord.Embed(
                title=f"Stats für {guild.name}",
                color=0x1f6feb
            )

            embed.add_field(
                name="Aktivität Übersicht",
                value=(
                    f"Nachrichten (7 Tage): `{msg_7}`\n"
                    f"Nachrichten (30 Tage): `{msg_30}`\n"
                    f"Voice (7 Tage): `{voice_7}` Min\n"
                    f"Voice (30 Tage): `{voice_30}` Min"
                ),
                inline=False
            )

            embed.add_field(
                name="Top Channel (7 Tage)",
                value=top_channel_text,
                inline=False
            )

            embed.add_field(
                name="🏆 Aktivste Nutzer (Nachrichten)",
                value=ranking_text,
                inline=True
            )

            embed.add_field(
                name="🎙️ Aktivste Nutzer (Voice)",
                value=voice_ranking_text,
                inline=True
            )

            # Chart
            dates = [start_7 + timedelta(days=i) for i in range(7)]
            data = {r["date"]: r for r in rows_7}
            msg_values = [data.get(d, {}).get("messages", 0) for d in dates]
            voice_values = [data.get(d, {}).get("voice_minutes", 0) for d in dates]

            chart = self.create_chart(
                f"{guild.name} • 7 Tage Übersicht",
                dates,
                msg_values,
                voice_values
            )

        file = discord.File(chart, filename="analytics.png")
        embed.set_image(url="attachment://analytics.png")
        embed.set_footer(text="Astra Analytics System")

        await interaction.edit_original_response(
            embed=embed,
            attachments=[file]
        )

    # =====================================================
    # COMMANDS
    # =====================================================

    statistik = app_commands.Group(
        name="statistik",
        description="Astra Analytics System",
        guild_only=True
    )

    @statistik.command(name="server", description="Zeigt die Aktivitäts-Statistiken eines Servers")
    async def server(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.send_stats(interaction, "server", 7)

    @statistik.command(name="user",  description="Zeigt die Aktivitäts-Statistiken eines Nutzers")
    async def user(self, interaction: discord.Interaction, member: discord.Member=None):
        await interaction.response.defer()
        if member is None:
            member = interaction.user
        await self.send_stats(interaction, "user", 7, member.id)

    @statistik.command(name="reset", description="Setzt alle Server-Statistiken zurück")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM analytics_messages WHERE guild_id=%s",
                                     (interaction.guild.id,))
                await cursor.execute("DELETE FROM analytics_voice WHERE guild_id=%s",
                                     (interaction.guild.id,))
                await cursor.execute("DELETE FROM analytics_daily_guild WHERE guild_id=%s",
                                     (interaction.guild.id,))

        await interaction.response.send_message(
            "Analytics erfolgreich zurückgesetzt.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Analytics(bot))
