import discord
import logging
import random
import asyncio
from datetime import datetime, timezone


class VoteView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Auch Voten",
                url="https://top.gg/bot/1113403511045107773/vote",
                emoji=discord.PartialEmoji(name="Herz", id=1361007251434901664)
            )
        )

def setup_topgg_events(bot):   # 👈 DAS IST DER FIX
    @bot.event
    async def on_dbl_vote(data):
        logging.info(f"on_dbl_vote ausgelöst für User: {data.get('user')}")

        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                # Test-Hook früh raus
                if data.get("type") == "test":
                    return bot.dispatch("dbl_test", data)

                # --- User/Guild/Objekte ---
                user_id = int(data["user"])
                user = bot.get_user(user_id)
                if user is None:
                    try:
                        user = await bot.fetch_user(user_id)
                    except Exception:
                        logging.error(f"User {user_id} nicht gefunden")
                        return

                guild = bot.get_guild(1141116981697859736)
                if not guild:
                    logging.error("Guild nicht gefunden!")
                    return

                voterole = guild.get_role(1141116981756575875)
                channel = guild.get_channel(1361006871753789532)

                # --- Zeit/Vote-Logik ---
                now_utc = datetime.now(timezone.utc)
                now_ts = int(now_utc.timestamp())
                next_vote_ts = now_ts + 12 * 3600
                this_month = now_utc.date().replace(day=1)
                vote_increase = 2 if now_utc.weekday() in (4, 5, 6) else 1

                # --- DB lesen ---
                await cur.execute(
                    """
                    SELECT count, last_reset, last_vote_epoch, streak, best_streak
                    FROM topgg
                    WHERE userID = %s
                    FOR UPDATE
                    """,
                    (user_id,)
                )
                row = await cur.fetchone()

                # --- DUPLICATE-SCHUTZ ---
                if row:
                    _, _, last_vote_epoch, _, _ = row
                    if last_vote_epoch and now_ts - int(last_vote_epoch) < 600:
                        logging.warning(f"[Vote] Duplicate Vote ignoriert ({user_id})")
                        return None

                # =============================
                # USER EXISTIERT NICHT
                # =============================
                streak_increased_today = False  # default
                if not row:
                    member_votes = vote_increase
                    streak = 1
                    best_streak = 1
                    streak_increased_today = True  # default

                    await cur.execute(
                        """
                        INSERT INTO topgg(userID, count, last_reset, last_vote, last_vote_epoch, next_vote_epoch, streak, best_streak)
                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            user_id,
                            member_votes,
                            this_month,
                            now_utc,
                            now_ts,
                            next_vote_ts,
                            streak,
                            best_streak
                        )
                    )

                # =============================
                # USER EXISTIERT
                # =============================
                else:
                    count, last_reset, last_vote_epoch, streak, best_streak = row

                    # Monatsreset
                    if not last_reset or last_reset < this_month:
                        count = 0
                        last_reset = this_month

                    member_votes = count + vote_increase

                    # --- DAILY STREAK LOGIK ---
                    # --- DAILY STREAK LOGIK ---

                    if last_vote_epoch is not None:
                        last_vote_date = datetime.fromtimestamp(int(last_vote_epoch), timezone.utc).date()
                        today = now_utc.date()

                        days_diff = (today - last_vote_date).days

                        if days_diff == 0:
                            pass
                        elif days_diff == 1:
                            streak += 1
                            streak_increased_today = True
                        else:
                            streak = 1
                            streak_increased_today = True
                    else:
                        streak = 1
                        streak_increased_today = True

                    if streak > best_streak:
                        best_streak = streak

                    await cur.execute(
                        """
                        UPDATE topgg
                        SET count = %s, last_reset = %s, last_vote = %s, last_vote_epoch = %s, next_vote_epoch = %s, streak = %s, best_streak = %s
                        WHERE userID = %s
                        """,
                        (
                            member_votes,
                            last_reset,
                            now_utc,
                            now_ts,
                            next_vote_ts,
                            streak,
                            best_streak,
                            user_id
                        )
                    )

                # =============================
                # ECONOMY-REWARD (MIT MULTIPLIER)
                # =============================
                base_amount = random.randint(15, 25)

                if streak_increased_today:
                    multiplier = min(1 + (streak - 1) * 0.05, 2.5)
                else:
                    multiplier = 1

                total_amount = round(base_amount * multiplier)

                await cur.execute(
                    """
                    INSERT INTO economy_users (user_id, wallet)
                        VALUES (%s, %s) AS new
                    ON DUPLICATE KEY UPDATE wallet = wallet + new.wallet
                    """,
                    (user_id, total_amount)
                )

                # --- Gesamtvotes für aktuellen Monat ---
                await cur.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM topgg WHERE last_reset = %s",
                    (this_month,)
                )
                row = await cur.fetchone()
                total_votes = row[0] if row and row[0] is not None else 0

        # =============================
        # EMBED
        # =============================
        embed = discord.Embed(
            title="Danke fürs Voten von Astra",
            description=(
                f"<:Astra_boost:1141303827107164270> `{user}({user.id})` hat für **Astra** gevotet.\n"
                f"Wir haben nun `{total_votes}` in diesem Monat.\n"
                f"Du hast diesen Monat bereits **{member_votes}** Mal gevotet.\n\n"
                "Du kannst alle 12 Stunden **[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
            ),
            colour=discord.Colour.blue(),
            timestamp=now_utc
        )

        embed.set_thumbnail(
            url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
        )
        embed.set_footer(
            text="Danke für deinen Support",
            icon_url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
        )

        # --- BELohnungstext für Nachricht ---
        streak_bonus = total_amount - base_amount

        if streak_bonus > 0:
            reward_text = (
                f"<:Astra_gw1:1141303852889550928> **Deine Belohnung:** {base_amount} Coins + {streak_bonus} Streak-Bonus "
                f"(Streak {streak}) <:Coin:1359178077011181811>"
            )
        else:
            reward_text = (
                f"<:Astra_gw1:1141303852889550928> **Deine Belohnung:** {total_amount} Coins "
                f"(Streak {streak}) <:Coin:1359178077011181811>"
            )

        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                member = None

        if member and voterole:
            try:
                await member.add_roles(voterole, reason="Voterole vergeben (Vote erkannt)")
            except Exception as e:
                logging.error(f"Fehler beim Hinzufügen der Rolle an {user_id}: {e}")

        try:
            if channel:
                await channel.send(
                    reward_text,
                    embed=embed,
                    view=VoteView()
                )
        except Exception as e:
            logging.error(f"Fehler beim Senden im Channel: {e}")

        when = datetime.fromtimestamp(next_vote_ts, timezone.utc)
        asyncio.create_task(bot.funktion2(user_id, when))

        return None




    @bot.event
    async def on_dbl_test(data):
        """An event that is called whenever someone tests the webhook system for your bot on Top.gg."""
        logging.info(f"on_dbl_test ausgelöst: {data!r}")

        guild = bot.get_guild(1141116981697859736)
        if guild is None:
            logging.error("Guild 1141116981697859736 nicht gefunden")
            return

        channel = guild.get_channel(1361006871753789532)
        if channel is None:
            logging.error("Channel 1361006871753789532 nicht gefunden")
            return

        # User
        user_id = int(data.get("user", 0))
        user = bot.get_user(user_id)
        user_display = f"{user}({user.id})" if user else f"Unbekannt ({user_id})"

        # Bot (Astra)
        astra = bot.get_user(int(data.get("bot", bot.user.id)))

        # Gesamtvotes aus eigener DB für aktuellen Monat
        now_utc = datetime.now(timezone.utc)
        this_month = now_utc.date().replace(day=1)

        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COALESCE(SUM(count), 0) FROM topgg WHERE last_reset = %s",
                    (this_month,)
                )
                row = await cur.fetchone()
                total_votes = row[0] if row and row[0] is not None else 0

        embed = discord.Embed(
            title="Test Vote Erfolgreich",
            description=(
                f"<:Astra_boost:1141303827107164270> `{user_display}` hat für {astra} gevotet.\n"
                f"Wir haben nun `{total_votes}` Votes diesen Monat.\n\n"
                "Du kannst alle 12 Stunden **[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
            ),
            colour=discord.Colour.red(),
            timestamp=now_utc
        )
        embed.set_thumbnail(
            url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
        )
        embed.set_footer(
            text="Danke für deinen Support",
            icon_url="https://media.discordapp.net/attachments/813029623277158420/901963417223573524/Idee_2_blau.jpg"
        )

        msg = await channel.send(embed=embed)
        heart = bot.get_emoji(1361007251434901664)
        if heart:
            await msg.add_reaction(heart)