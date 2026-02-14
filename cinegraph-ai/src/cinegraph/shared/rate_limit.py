"""Redis-backed counters shared across processes, with atomic expiration."""

import hashlib

SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
if count <= tonumber(ARGV[1]) then return 1 else return 0 end
"""


class RateLimitUnavailable(RuntimeError):
    """The rate-limit backend cannot be reached; callers must deny the request."""


class RedisRateLimiter:
    def __init__(self, url, client=None):
        if client is None:
            import redis

            client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        self.client = client

    def allow(self, scope, identity, limit, window):
        digest = hashlib.sha256(str(identity).encode()).hexdigest()
        key = f"cinegraph:limit:{scope}:{digest}"
        try:
            return bool(self.client.eval(SCRIPT, 1, key, limit, window))
        except Exception as exc:
            raise RateLimitUnavailable("Rate limit service unavailable") from exc

    def ping(self):
        try:
            return bool(self.client.ping())
        except Exception as exc:
            raise RateLimitUnavailable("Rate limit service unavailable") from exc

    def close(self):
        self.client.close()
