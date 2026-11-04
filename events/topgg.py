
import discord
import logging
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
                emoji=discord.PartialEmoji(
                    name="Herz",
                    id=1361007251434901664
                )
            )
        )


def setup_topgg_events(bot):

    async def process_topgg_vote(data):
        """Verarbeitet einen eingegangenen Top.gg-Vote."""

        if bot.pool is None:
            logging.error("[Top.gg] Kein Datenbank-Pool verfügbar.")
            return

        user_id = int(data["user"])
        vote_increase = int(data.get("weight", 1))

        guild = bot.get_guild(1141116981697859736)

        if guild is None:
            logging.error("[Top.gg] Support-Server nicht gefunden.")
            return

        try:
            user = guild.get_member(user_id)

            if user is None:
                user = await guild.fetch_member(user_id)

        except discord.NotFound:
            user = bot.get_user(user_id)

            if user is None:
                user = await bot.fetch_user(user_id)

        if user is None:
            logging.error("[Top.gg] User %s nicht gefunden.", user_id)
            return

        voterole = guild.get_role(1141116981756575875)
        channel = guild.get_channel(1361006871753789532)

        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())
        next_vote_ts = now_ts + 12 * 3600
        this_month = now_utc.date().replace(day=1)

        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

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

                # Duplikatschutz
                if row:
                    _, _, last_vote_epoch, _, _ = row

                    if (
                        last_vote_epoch
                        and now_ts - int(last_vote_epoch) < 600
                    ):
                        logging.warning(
                            "[Top.gg] Doppelter Vote ignoriert (User: %s)",
                            user_id
                        )
                        return

                streak_increased_today = False

                # Neuer User
                if not row:
                    member_votes = vote_increase
                    streak = 1
                    best_streak = 1
                    streak_increased_today = True

                    await cur.execute(
                        """
                        INSERT INTO topgg(
                            userID,
                            count,
                            last_reset,
                            last_vote,
                            last_vote_epoch,
                            next_vote_epoch,
                            streak,
                            best_streak
                        )
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

                # Bereits vorhandener User
                else:
                    count, last_reset, last_vote_epoch, streak, best_streak = row

                    # Monatsreset
                    if not last_reset or last_reset < this_month:
                        count = 0
                        last_reset = this_month

                    member_votes = count + vote_increase

                    # Streak berechnen
                    if last_vote_epoch is not None:
                        last_vote_date = datetime.fromtimestamp(
                            int(last_vote_epoch),
                            timezone.utc
                        ).date()

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
                        SET
                            count = %s,
                            last_reset = %s,
                            last_vote = %s,
                            last_vote_epoch = %s,
                            next_vote_epoch = %s,
                            streak = %s,
                            best_streak = %s
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

                # Coins vergeben
                base_amount = 20
                streak_bonus = streak if streak_increased_today else 0
                total_amount = base_amount + streak_bonus

                await cur.execute(
                    """
                    INSERT INTO economy_users (user_id, wallet)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE
                        wallet = wallet + VALUES(wallet)
                    """,
                    (user_id, total_amount)
                )

                # Gesamtvotes des aktuellen Monats
                await cur.execute(
                    """
                    SELECT COALESCE(SUM(count), 0)
                    FROM topgg
                    WHERE last_reset = %s
                    """,
                    (this_month,)
                )

                row = await cur.fetchone()
                total_votes = row[0] if row and row[0] is not None else 0

        # Vote-Embed
        embed = discord.Embed(
            title="Danke fürs Voten von Astra",
            description=(
                f"<:Astra_boost:1141303827107164270> "
                f"`{user}({user.id})` hat für **Astra** gevotet.\n"
                f"Wir haben nun `{total_votes}` in diesem Monat.\n"
                f"Du hast diesen Monat bereits **{member_votes}** Mal gevotet.\n\n"
                "Du kannst alle 12 Stunden "
                "**[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
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

        # Belohnungstext
        if streak_bonus > 0:
            reward_text = (
                "<:Astra_gw1:1141303852889550928> "
                f"**Deine Belohnung:** {base_amount} Coins + "
                f"{streak_bonus} Streak-Bonus "
                f"(Streak {streak}) <:Coin:1359178077011181811>"
            )
        else:
            reward_text = (
                "<:Astra_gw1:1141303852889550928> "
                f"**Deine Belohnung:** {base_amount} Coins "
                f"(Streak {streak}) <:Coin:1359178077011181811>"
            )

        # Voterolle vergeben
        member = guild.get_member(user_id)

        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                member = None
            except discord.HTTPException:
                logging.exception(
                    "[Top.gg] Mitglied konnte nicht geladen werden: %s",
                    user_id
                )

        if member and voterole:
            try:
                await member.add_roles(
                    voterole,
                    reason="Voterole vergeben (Top.gg Vote)"
                )
            except discord.Forbidden:
                logging.error(
                    "[Top.gg] Keine Berechtigung für die Voterolle von %s.",
                    user_id
                )
            except discord.HTTPException:
                logging.exception(
                    "[Top.gg] Fehler beim Vergeben der Voterolle für %s.",
                    user_id
                )

        # Vote-Nachricht senden
        if channel:
            try:
                await channel.send(
                    reward_text,
                    embed=embed,
                    view=VoteView()
                )
            except discord.HTTPException:
                logging.exception(
                    "[Top.gg] Vote-Nachricht konnte nicht gesendet werden."
                )

        # Vote-Reminder planen
        when = datetime.fromtimestamp(next_vote_ts, timezone.utc)

        asyncio.create_task(
            bot.funktion2(user_id, when)
        )

        logging.info(
            "[Top.gg] Vote erfolgreich verarbeitet: User=%s, Gewicht=%s, Event-ID=%s",
            user_id,
            vote_increase,
            data.get("event_id")
        )

    @bot.event
    async def on_dbl_vote(data):
        logging.info(
            "[Top.gg] Vote-Event empfangen: User=%s, Gewicht=%s, Event-ID=%s",
            data.get("user"),
            data.get("weight", 1),
            data.get("event_id")
        )

        try:
            await process_topgg_vote(data)

        except asyncio.CancelledError:
            raise

        except Exception:
            logging.exception(
                "[Top.gg] Fehler bei der Vote-Verarbeitung (User=%s, Event-ID=%s)",
                data.get("user"),
                data.get("event_id")
            )

    @bot.event
    async def on_dbl_test(data):
        """Verarbeitet einen Top.gg-Test-Webhook."""

        logging.info("[Top.gg] Test-Webhook empfangen: %s", data)

        guild = bot.get_guild(1141116981697859736)

        if guild is None:
            logging.error("[Top.gg] Support-Server nicht gefunden.")
            return

        channel = guild.get_channel(1361006871753789532)

        if channel is None:
            logging.error("[Top.gg] Vote-Channel nicht gefunden.")
            return

        user_id = int(data.get("user", 0))
        user = bot.get_user(user_id)

        user_display = (
            f"{user}({user.id})"
            if user
            else f"Unbekannt ({user_id})"
        )

        astra = bot.user

        now_utc = datetime.now(timezone.utc)
        this_month = now_utc.date().replace(day=1)

        async with bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COALESCE(SUM(count), 0)
                    FROM topgg
                    WHERE last_reset = %s
                    """,
                    (this_month,)
                )

                row = await cur.fetchone()
                total_votes = row[0] if row and row[0] is not None else 0

        embed = discord.Embed(
            title="Test Vote Erfolgreich",
            description=(
                f"<:Astra_boost:1141303827107164270> "
                f"`{user_display}` hat für {astra} gevotet!\n"
                f"Wir haben nun `{total_votes}` Votes diesen Monat.\n\n"
                "Du kannst alle 12 Stunden "
                "**[hier](https://top.gg/bot/1113403511045107773/vote)** voten."
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
