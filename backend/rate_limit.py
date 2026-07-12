"""In-memory per-IP rate limiting for the expensive /api/research endpoint. A single-process
in-memory counter is fine here since this app runs as one instance; a multi-instance deployment
would need a shared store (e.g. Redis) instead."""
import time
from collections import defaultdict

from fastapi import HTTPException, Request

_WINDOW_SECONDS = 60
_MAX_REQUESTS = 5
_hits: dict[str, list[float]] = defaultdict(list)


def enforce_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    hits = _hits[ip]
    hits[:] = [t for t in hits if now - t < _WINDOW_SECONDS]
    if len(hits) >= _MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests — max {_MAX_REQUESTS} searches per {_WINDOW_SECONDS}s. Please wait a moment.",
        )
    hits.append(now)
