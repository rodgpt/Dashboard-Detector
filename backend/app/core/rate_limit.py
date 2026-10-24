"""In-process login throttle (R-2.4). Sufficient for a single container.

If this ever runs multiple replicas, move the counter to shared state.
"""
import time
from collections import defaultdict

_FAILS: dict[str, list[float]] = defaultdict(list)
WINDOW_S = 300
MAX_FAILS = 5


def too_many(key: str) -> bool:
    now = time.time()
    recent = [t for t in _FAILS.get(key, ()) if now - t < WINDOW_S]
    if recent:
        _FAILS[key] = recent
    else:
        # Evict, do not keep an empty list per key: an attacker spraying
        # addresses grew this dict without bound (review BE-07a).
        _FAILS.pop(key, None)
    return len(recent) >= MAX_FAILS


def record_failure(key: str) -> None:
    _FAILS[key].append(time.time())


def clear(key: str) -> None:
    _FAILS.pop(key, None)
