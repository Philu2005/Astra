from datetime import datetime
from zoneinfo import ZoneInfo
import discord
import asyncio

BERLIN_TZ = ZoneInfo("Europe/Berlin")

async def rotating_presence(client: discord.Client):
    await client.wait_until_ready()

    server_count = 0
    member_count = 0
    last_update = 0

    while not client.is_closed():
        try:
            # 🛑 Warten wenn Bot nicht ready (Reconnect etc.)
            if not client.is_ready():
                await asyncio.sleep(5)
                continue

            # 🕒 Deutsche Zeit erzwingen
            now = datetime.now(BERLIN_TZ)
            current_time = now.timestamp()

            # 🔄 Stats nur alle 5 Minuten neu berechnen
            if current_time - last_update > 300:
                server_count = len(client.guilds)
                member_count = sum(g.member_count or 0 for g in client.guilds)
                last_update = current_time

            # 🇩🇪 Deutsche Tausendertrennung
            server_str = f"{server_count:,}".replace(",", ".")
            member_str = f"{member_count:,}".replace(",", ".")

            # 🌙 Idle zwischen 00:00–06:00 deutscher Zeit
            astra_status = discord.Status.idle if 0 <= now.hour < 6 else discord.Status.online

            activities = [
                discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"🔹 {server_str} Server"
                ),
                discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"🔹 {member_str} Mitglieder"
                ),
                discord.Activity(
                    type=discord.ActivityType.watching,
                    name="⚙️ Interaktives Setup"
                ),
                discord.Activity(
                    type=discord.ActivityType.watching,
                    name="🎫 Modernes Ticket-System"
                ),
            ]

            for activity in activities:
                try:
                    # ❗ zusätzlicher Schutz während Reconnect
                    if client.is_closed() or not client.is_ready():
                        break

                    await client.change_presence(
                        activity=activity,
                        status=astra_status
                    )

                except Exception as e:
                    print(f"[Presence Error] {e}")
                    await asyncio.sleep(5)
                    break  # verhindert Error-Spam

                await asyncio.sleep(30)

        except Exception as e:
            # 🧠 Falls irgendwas im Loop selbst crasht → weiterlaufen
            print(f"[Presence Loop Crash] {e}")
            await asyncio.sleep(10)