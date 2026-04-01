import re
import logger
from pathlib import Path

SCHEMA_PATH = "/root/Astra/opt/schema.sql"


async def table_exists(cur, table_name: str) -> bool:
    await cur.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = %s
        LIMIT 1
    """, (table_name,))
    return await cur.fetchone() is not None


async def table_has_data(cur, table_name: str) -> bool:
    try:
        await cur.execute(f"SELECT 1 FROM `{table_name}` LIMIT 1")
        return await cur.fetchone() is not None
    except Exception:
        return False


def extract_table_name(stmt: str, keyword: str):
    pattern = rf"{keyword}\s+(?:IF NOT EXISTS\s+)?`?([a-zA-Z0-9_]+)`?"
    match = re.search(pattern, stmt, re.IGNORECASE)
    return match.group(1) if match else None


def split_sql_statements(sql: str):
    statements = []
    current = []
    in_string = False

    for char in sql:
        if char == "'":
            in_string = not in_string

        if char == ";" and not in_string:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)

    if current:
        stmt = "".join(current).strip()
        if stmt:
            statements.append(stmt)

    return statements


async def run_sql_file(pool):
    p = Path(SCHEMA_PATH)
    if not p.exists():
        logging.error(f"[DB] SQL-Datei nicht gefunden: {SCHEMA_PATH}")
        return

    raw = p.read_text(encoding="utf-8")

    # Kommentare entfernen
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"--.*$", "", raw, flags=re.M)

    statements = split_sql_statements(raw)

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:

            skipped_tables = 0
            skipped_inserts = 0
            executed = 0

            for stmt in statements:
                stmt = stmt.strip()
                if not stmt:
                    continue

                try:
                    stmt_upper = stmt.upper()

                    # ------------------------
                    # CREATE TABLE
                    # ------------------------
                    if "CREATE TABLE" in stmt_upper:
                        table_name = extract_table_name(stmt, "CREATE TABLE")

                        if table_name and await table_exists(cur, table_name):
                            skipped_tables += 1
                            continue

                    # ------------------------
                    # DROP TABLE
                    # ------------------------
                    elif "DROP TABLE" in stmt_upper:
                        table_name = extract_table_name(stmt, "DROP TABLE")

                        if table_name and not await table_exists(cur, table_name):
                            continue

                    # ------------------------
                    # INSERT
                    # ------------------------
                    elif "INSERT INTO" in stmt_upper:
                        table_name = extract_table_name(stmt, "INSERT INTO")

                        if table_name:
                            # Speziell für deine Quiz-Daten
                            if table_name == "emojiquiz_quizzez":
                                await cur.execute("SELECT COUNT(*) FROM emojiquiz_quizzez")
                                count = (await cur.fetchone())[0]

                                if count > 0:
                                    skipped_inserts += 1
                                    continue
                            else:
                                if await table_has_data(cur, table_name):
                                    skipped_inserts += 1
                                    continue

                    # ------------------------
                    # EXECUTE
                    # ------------------------
                    await cur.execute(stmt)
                    executed += 1

                except Exception as e:
                    logging.error(f"[DB] Fehler in Statement:\n{stmt}\n{e}")

        await conn.commit()

    # 🔥 EIN sauberer Log
    logging.info(
        f"[DB] Done | Executed: {executed} | "
        f"Tables skipped: {skipped_tables} | "
        f"Inserts skipped: {skipped_inserts} | "
        f"Total: {len(statements)}"
    )