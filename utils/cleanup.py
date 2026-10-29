import asyncio
import logging

async def cleanup_logs_task(bot):
    while True:
        try:
            if bot.pool:
                async with bot.pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            DELETE FROM bot_logs
                            WHERE created_at < NOW() - INTERVAL 7 DAY
                        """)

                logging.info("[CLEANUP] Alte Logs gelöscht")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.exception(f"[CLEANUP ERROR] {e}")

        await asyncio.sleep(3600)  # 1 Stunde