"""In-memory sliding-window rate limits for one process. Enough for a single small server;
behind several workers, put the limits in Redis or at the proxy."""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "") if settings.trust_proxy else ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def hit(key: str, limit: int, window: int) -> bool:
    """Record one hit; False when the key went over `limit` hits in `window` seconds."""
    now = time.monotonic()
    with _lock:
        bucket = _hits[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def limiter(name: str, limit: int, window: int):
    async def dependency(request: Request) -> None:
        if request.method != "POST":
            return
        if not hit(f"{name}:{client_ip(request)}", limit, window):
            raise HTTPException(status_code=429, detail="too many requests")
    return dependency


def reset() -> None:
    with _lock:
        _hits.clear()
