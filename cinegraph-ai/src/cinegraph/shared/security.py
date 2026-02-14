"""Private API authentication and bounded request middleware."""

import asyncio
import hmac
import ipaddress
import os

from starlette.responses import JSONResponse

from cinegraph.shared.rate_limit import RateLimitUnavailable, RedisRateLimiter
from cinegraph.shared.runtime import flag, validate_runtime


def forwarded_client_ip(value, fallback):
    """Parse one address, never an appended chain or an arbitrary bucket key."""
    try:
        if "%" in value:
            return fallback
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return fallback


class SanitizeProxyClientIP:
    """Use only behind ingress that overwrites XFF and blocks direct access.

    This wrapper runs before ProxyFix. Merely enabling this option on a publicly
    reachable application would let callers impersonate clients and evade limits.
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        environ["HTTP_X_FORWARDED_FOR"] = forwarded_client_ip(
            environ.get("HTTP_X_FORWARDED_FOR", ""), environ.get("REMOTE_ADDR", "unknown")
        )
        return self.app(environ, start_response)


PROBES = {"/live", "/ready", "/health"}
MAX_BODY = 16 * 1024


class APISecurityMiddleware:
    def __init__(self, app, owner, runtime):
        self.app, self.owner, self.runtime = app, owner, runtime

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {key.lower(): value for key, value in scope.get("headers", [])}

        async def deny(status, detail, retry=None):
            response = JSONResponse(
                {"detail": detail}, status_code=status, headers={"Retry-After": str(retry)} if retry else None
            )
            await response(scope, receive, send)

        if self.runtime.require_auth and path not in PROBES:
            expected = f"Bearer {self.runtime.api_key}".encode()
            if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
                return await deny(401, "Authentication required")
            limiter = self.owner.state.rate_limiter
            try:
                allowed = await asyncio.to_thread(
                    limiter.allow, "api", "service", int(os.getenv("API_RATE_LIMIT", "240")), 60
                )
                if allowed and path == "/chat":
                    allowed = await asyncio.to_thread(
                        limiter.allow, "chat", "service", int(os.getenv("CHAT_RATE_LIMIT", "20")), 60
                    )
            except RateLimitUnavailable:
                return await deny(503, "Request protection unavailable")
            if not allowed:
                return await deny(429, "Too many requests", 60)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await deny(400, "Invalid content length")
        if length > MAX_BODY or length < 0:
            return await deny(413, "Request body is too large")
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_BODY:
                        return await deny(413, "Request body is too large")
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await deny(408, "Request body timed out")
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def install_api_security(app):
    runtime = validate_runtime()
    app.state.security_runtime = runtime
    app.state.rate_limiter = RedisRateLimiter(runtime.redis_url) if runtime.require_auth else None
    app.add_middleware(APISecurityMiddleware, owner=app, runtime=runtime)


def check_security_readiness(app):
    """Synchronous dependency check; invoke in a sync route or worker thread."""
    if app.state.security_runtime.require_auth:
        app.state.rate_limiter.ping()


def close_api_security(app):
    """Close the Redis pool during API lifespan shutdown."""
    if app.state.rate_limiter is not None:
        app.state.rate_limiter.close()


class CatalogLoginThrottle:
    """Protect the separate Django admin sign-in endpoint across workers."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.trust_proxy = flag("DJANGO_TRUST_PROXY")
        runtime = validate_runtime()
        self.limiter = RedisRateLimiter(runtime.redis_url) if runtime.require_auth else None

    def __call__(self, request):
        if (
            self.limiter is not None
            and request.method == "POST"
            and request.path.rstrip("/") == "/admin/login"
        ):
            from django.http import JsonResponse

            try:
                client_ip = request.META.get("REMOTE_ADDR", "unknown")
                if self.trust_proxy:
                    client_ip = forwarded_client_ip(request.META.get("HTTP_X_FORWARDED_FOR", ""), client_ip)
                ip_allowed = self.limiter.allow("catalog-login-ip", client_ip, 30, 900)
                username = request.POST.get("username", "")[:150].strip().casefold()
                user_allowed = self.limiter.allow("catalog-login-user", username, 10, 900)
            except RateLimitUnavailable:
                return JsonResponse({"error": "Request protection unavailable"}, status=503)
            if not ip_allowed or not user_allowed:
                response = JsonResponse({"error": "Too many sign-in attempts. Try again later."}, status=429)
                response["Retry-After"] = "900"
                return response
        return self.get_response(request)
