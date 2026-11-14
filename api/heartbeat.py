import threading
import time
from copy import deepcopy


class HeartbeatState:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_payload: dict | None = None
        self._last_received_ts: float | None = None

    def update(self, payload: dict) -> float:
        received_ts = time.time()
        with self._lock:
            self._last_payload = deepcopy(payload)
            self._last_received_ts = received_ts
        return received_ts

    def snapshot(self) -> tuple[dict | None, float | None]:
        with self._lock:
            payload = deepcopy(self._last_payload) if self._last_payload is not None else None
            received_ts = self._last_received_ts
        return payload, received_ts


heartbeat_state = HeartbeatState()


def derive_bot_status(
    payload: dict | None,
    received_ts: float | None,
    stale_after_seconds: float,
    now_ts: float | None = None,
) -> dict:
    now = now_ts if now_ts is not None else time.time()
    base = {
        "online": False,
        "status": "unknown",
        "last_heartbeat": None,
        "stale_after_seconds": stale_after_seconds,
    }

    if payload is None or received_ts is None:
        return base

    age_seconds = max(0.0, now - received_ts)
    base["last_heartbeat"] = payload.get("last_heartbeat")
    base["heartbeat_age_seconds"] = round(age_seconds, 2)

    if age_seconds > stale_after_seconds:
        base["status"] = "offline"
        return base

    connected = bool(payload.get("gateway_connected", False))
    is_ready = bool(payload.get("is_ready", False))
    is_connecting = bool(payload.get("is_connecting", False))

    if connected and is_ready:
        base["status"] = "online"
        base["online"] = True
    elif is_connecting or (connected and not is_ready):
        base["status"] = "connecting"
    else:
        base["status"] = "offline"

    shards = payload.get("shards")
    if isinstance(shards, list):
        base["shards"] = shards

    return base
