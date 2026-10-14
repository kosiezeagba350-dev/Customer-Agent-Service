import time
from collections import defaultdict

from fastapi import HTTPException, Request

HITS: dict[str, list] = defaultdict(list)


def rate_limit(key: str, limit: int = 30, window: int = 60):
    now = time.time()
    hits = [t for t in HITS[key] if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(429, "Too many requests. Please wait a minute.")
    hits.append(now)
    HITS[key] = hits


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
