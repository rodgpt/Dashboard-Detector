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
    _FAILS[key] = [t for t in _FAILS[key] if now - t < WINDOW_S]
    return len(_FAILS[key]) >= MAX_FAILS


def record_failure(key: str) -> None:
    _FAILS[key].append(time.time())


def clear(key: str) -> None:
    _FAILS.pop(key, None)
