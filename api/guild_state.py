import threading
import time
from copy import deepcopy


class GuildStateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._guilds: dict[int, dict] = {}
        self._stats: dict[str, int] = {"users": 0, "guilds": 0, "commands": 0}
        self._last_full_sync_ts: float | None = None
        self._last_update_ts: float | None = None
        self._last_successful_sync_at: str | None = None

    def replace_all(self, guilds: list[dict], stats: dict[str, int], last_updated: str | None) -> dict:
        normalized: dict[int, dict] = {}
        for guild in guilds:
            guild_id = _extract_int(guild.get("id"))
            if guild_id is None:
                continue
            normalized[guild_id] = deepcopy(guild)

        normalized_stats = {
            "users": max(0, int(stats.get("users", 0))),
            "guilds": max(0, int(stats.get("guilds", 0))),
            "commands": max(0, int(stats.get("commands", 0))),
        }

        now = time.time()
        with self._lock:
            self._guilds = normalized
            self._stats = normalized_stats
            self._last_full_sync_ts = now
            self._last_update_ts = now
            self._last_successful_sync_at = last_updated

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

    def stats_snapshot(self) -> tuple[dict[str, int], str | None, float | None]:
        with self._lock:
            stats = deepcopy(self._stats)
            last_sync = self._last_successful_sync_at
            full_sync_ts = self._last_full_sync_ts
        return stats, last_sync, full_sync_ts


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
