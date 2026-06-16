import asyncio

async def cleanup_logs_task(bot):
    while True:
        try:
            async with bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        DELETE FROM bot_logs
                        WHERE created_at < NOW() - INTERVAL 7 DAY
                    """)

            print("[CLEANUP] Alte Logs gelöscht")

        except Exception as e:
            print("[CLEANUP ERROR]", e)

        await asyncio.sleep(3600)  # 1 Stunde