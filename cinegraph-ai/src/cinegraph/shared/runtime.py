"""Fail-closed environment checks shared by every service entry point."""

import os
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def flag(name, default=False):
    value = os.getenv(name, str(default)).lower()
    if value not in _TRUE | _FALSE:
        raise ValueError(f"{name} must be true or false")
    return value in _TRUE


def _strong(name, minimum, value=None):
    if value is None:
        value = os.getenv(name, "")
    weak = ("change", "default", "example", "development", "cinegraph-local", "password123")
    if len(value) < minimum or len(set(value)) < 4 or any(word in value.lower() for word in weak):
        raise ValueError(f"{name} must be a unique strong secret of at least {minimum} characters")
    return value


@dataclass(frozen=True)
class Runtime:
    production: bool
    require_auth: bool
    api_key: str
    redis_url: str
    dashboard_origin: str
    catalog_origin: str


def validate_runtime():
    environment = os.getenv("CINEGRAPH_ENV", "development").lower()
    if environment not in {"production", "development", "test"}:
        raise ValueError("CINEGRAPH_ENV must be development, test, or production")
    production = environment == "production"
    auth = flag("CINEGRAPH_REQUIRE_AUTH", production)
    if production and not auth:
        raise ValueError("CINEGRAPH_REQUIRE_AUTH cannot be false in production")
    if production and any(flag(key) for key in ("DJANGO_DEBUG", "FLASK_DEBUG", "DEBUG")):
        raise ValueError("DJANGO_DEBUG, FLASK_DEBUG and DEBUG must be false in production")
    redis_url = os.getenv("REDIS_URL", "")
    if auth:
        _strong("CINEGRAPH_API_KEY", 32)
        _strong("DJANGO_SECRET_KEY", 50 if production else 32)
        if urlsplit(redis_url).scheme not in {"redis", "rediss", "unix"}:
            raise ValueError("REDIS_URL is required when CINEGRAPH_REQUIRE_AUTH is true")
    origins = {}
    for key in ("DASHBOARD_ORIGIN", "CATALOG_ORIGIN"):
        value = os.getenv(key, "").rstrip("/")
        parsed = urlsplit(value)
        if production and (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{key} must be an HTTPS origin without credentials or a path")
        origins[key] = value
    if production:
        database = urlsplit(os.getenv("DATABASE_URL", ""))
        if (
            database.scheme not in {"postgres", "postgresql"}
            or not database.hostname
            or not database.path.strip("/")
        ):
            raise ValueError("DATABASE_URL must reference PostgreSQL in production")
        _strong("DATABASE_URL", 16, unquote(database.password or ""))
        redis = urlsplit(redis_url)
        if redis.scheme in {"redis", "rediss"}:
            _strong("REDIS_URL", 16, unquote(redis.password or ""))
        _strong("NEO4J_PASSWORD", 16)
    return Runtime(
        production,
        auth,
        os.getenv("CINEGRAPH_API_KEY", ""),
        redis_url,
        origins["DASHBOARD_ORIGIN"],
        origins["CATALOG_ORIGIN"],
    )
