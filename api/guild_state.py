import threading
import time
from copy import deepcopy


class GuildStateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._guilds: dict[int, dict] = {}
        self._last_full_sync_ts: float | None = None
        self._last_update_ts: float | None = None

    def replace_all(self, guilds: list[dict]) -> dict:
        normalized: dict[int, dict] = {}
        for guild in guilds:
            guild_id = _extract_int(guild.get("id"))
            if guild_id is None:
                continue
            normalized[guild_id] = deepcopy(guild)

        now = time.time()
        with self._lock:
            self._guilds = normalized
            self._last_full_sync_ts = now
            self._last_update_ts = now

        return {
            "guilds": len(normalized),
            "full_sync_at": now,
        }

    def upsert_guild(self, guild: dict) -> bool:
        guild_id = _extract_int(guild.get("id"))
        if guild_id is None:
            return False

        now = time.time()
        with self._lock:
            self._guilds[guild_id] = deepcopy(guild)
            self._last_update_ts = now
            if self._last_full_sync_ts is None:
                self._last_full_sync_ts = now
        return True

    def remove_guild(self, guild_id: int | str) -> bool:
        parsed = _extract_int(guild_id)
        if parsed is None:
            return False

        now = time.time()
        with self._lock:
            removed = self._guilds.pop(parsed, None) is not None
            if removed:
                self._last_update_ts = now
        return removed

    def snapshot(self) -> tuple[dict[int, dict], float | None, float | None]:
        with self._lock:
            guilds = deepcopy(self._guilds)
            full_sync_ts = self._last_full_sync_ts
            update_ts = self._last_update_ts
        return guilds, full_sync_ts, update_ts


def _extract_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
        if parsed <= 0:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


guild_state_store = GuildStateStore()
