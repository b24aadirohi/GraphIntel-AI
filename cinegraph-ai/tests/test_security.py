"""Production controls must fail closed and authenticated sessions be revocable."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def secure_env(monkeypatch):
    values = {
        "CINEGRAPH_ENV": "production",
        "CINEGRAPH_REQUIRE_AUTH": "true",
        "CINEGRAPH_API_KEY": "aB8!" * 12,
        "DJANGO_SECRET_KEY": "sE9!" * 18,
        "DJANGO_DEBUG": "false",
        "DASHBOARD_ORIGIN": "https://films.example.test",
        "CATALOG_ORIGIN": "https://catalog.example.test",
        "DATABASE_URL": "postgresql://cinegraph:strong-db-password@postgres/cinegraph",
        "REDIS_URL": "redis://:strong-redis-password@redis:6379/0",
        "NEO4J_PASSWORD": "strong-graph-password",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_production_accepts_complete_configuration(secure_env):
    from cinegraph.shared.runtime import validate_runtime

    runtime = validate_runtime()
    assert runtime.production and runtime.require_auth


@pytest.mark.parametrize(
    "key,value",
    [
        ("CINEGRAPH_API_KEY", "short"),
        ("DJANGO_SECRET_KEY", "local-development-only-change-before-public-deployment"),
        ("DJANGO_DEBUG", "true"),
        ("CINEGRAPH_REQUIRE_AUTH", "false"),
        ("DASHBOARD_ORIGIN", "http://films.example.test"),
        ("CATALOG_ORIGIN", ""),
        ("DATABASE_URL", "sqlite:///:memory:"),
        ("REDIS_URL", ""),
        ("NEO4J_PASSWORD", "cinegraph-local-password"),
    ],
)
def test_production_rejects_insecure_configuration(secure_env, monkeypatch, key, value):
    from cinegraph.shared.runtime import validate_runtime

    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        validate_runtime()


class Limiter:
    def __init__(self, allowed=True, unavailable=False):
        self.allowed = allowed
        self.unavailable = unavailable
        self.calls = []

    def allow(self, scope, identity, limit, window):
        from cinegraph.shared.rate_limit import RateLimitUnavailable

        self.calls.append((scope, identity, limit, window))
        if self.unavailable:
            raise RateLimitUnavailable("secret redis host")
        return self.allowed


def protected_api(limiter):
    from cinegraph.shared.security import install_api_security

    app = FastAPI()
    install_api_security(app)
    app.state.rate_limiter = limiter

    @app.get("/live")
    def live():
        return {"status": "ok"}

    @app.api_route("/secret", methods=["GET", "POST"])
    def secret():
        return {"secret": "catalog"}

    @app.post("/chat")
    def chat():
        return {"answer": "ok"}

    return TestClient(app)


def test_api_auth_covers_docs_and_does_not_expose_probe_data(secure_env):
    client = protected_api(Limiter())
    assert client.get("/live").json() == {"status": "ok"}
    for path in ("/secret", "/docs", "/openapi.json", "/metrics"):
        assert client.get(path).status_code == 401
    assert client.get("/secret", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(
        "/secret", headers={"Authorization": f"Bearer {secure_env['CINEGRAPH_API_KEY']}"}
    ).json() == {"secret": "catalog"}


@pytest.mark.parametrize("limiter,status", [(Limiter(False), 429), (Limiter(unavailable=True), 503)])
def test_api_throttle_denies_and_fails_closed(secure_env, limiter, status):
    client = protected_api(limiter)
    response = client.get("/secret", headers={"Authorization": f"Bearer {secure_env['CINEGRAPH_API_KEY']}"})
    assert response.status_code == status
    assert "secret redis" not in response.text


def test_api_request_limit_rejects_chunked_body_and_does_not_trust_xff(secure_env):
    limiter = Limiter()
    client = protected_api(limiter)
    headers = {"Authorization": f"Bearer {secure_env['CINEGRAPH_API_KEY']}", "X-Forwarded-For": "1.2.3.4"}
    assert (
        client.post("/secret", content=iter([b"a" * 9000, b"b" * 9000]), headers=headers).status_code == 413
    )
    assert client.post("/chat", json={}, headers=headers).status_code == 200
    assert all(call[1] != "1.2.3.4" for call in limiter.calls)
    assert {call[0] for call in limiter.calls} >= {"api", "chat"}


def test_rate_limiter_uses_atomic_expiring_counter():
    from cinegraph.shared.rate_limit import RedisRateLimiter

    class Redis:
        def eval(self, script, keys, key, maximum, window):
            assert "INCR" in script and "EXPIRE" in script
            assert keys == 1 and maximum == 3 and window == 60
            assert "username" not in key
            return 1

    assert RedisRateLimiter("redis://localhost", client=Redis()).allow("login", "username", 3, 60)


@pytest.fixture
def login_app(monkeypatch, transactional_db):
    from cinegraph.dashboard.app import create_app

    monkeypatch.setenv("CINEGRAPH_ENV", "development")
    monkeypatch.setenv("CINEGRAPH_REQUIRE_AUTH", "true")
    monkeypatch.setenv("CINEGRAPH_API_KEY", "A-service-key-that-is-at-least-32-characters")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "A-session-key-that-is-at-least-50-characters-long-123456789")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    app = create_app({"TESTING": True})
    app.extensions["rate_limiter"] = Limiter()
    return app


def csrf(client):
    response = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert token
    return token.group(1)


def login(client, username="viewer", password="a-test-password"):
    return client.post(
        "/login", data={"username": username, "password": password, "csrf_token": csrf(client)}
    )


@pytest.fixture
def user(transactional_db, django_user_model):
    return django_user_model.objects.create_user(username="viewer", password="a-test-password")


def test_dashboard_requires_login_and_csrf(login_app, user):
    client = login_app.test_client()
    assert client.get("/").status_code == 302
    assert client.get("/api/stats").status_code == 401
    assert (
        client.post("/login", data={"username": "viewer", "password": "a-test-password"}).status_code == 400
    )
    response = login(client)
    assert response.status_code == 302
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert client.get("/").status_code == 200
    assert client.post("/api/chat", json={"question": "test"}).status_code == 400
    assert client.post("/logout").status_code == 400
    token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text).group(1)
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302
    assert client.get("/").status_code == 302


@pytest.mark.parametrize("change", ["password", "inactive", "revoked", "expired"])
def test_dashboard_sessions_are_revocable(login_app, user, change):
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    client = login_app.test_client()
    assert login(client).status_code == 302
    if change == "password":
        user.set_password("new-password")
        user.save()
    elif change == "inactive":
        user.is_active = False
        user.save()
    elif change == "revoked":
        Session.objects.all().delete()
    else:
        Session.objects.update(expire_date=timezone.now())
    assert client.get("/api/stats").status_code == 401


def test_login_rate_limit_fails_closed_and_ignores_xff(login_app, user):
    client = login_app.test_client()
    token = csrf(client)
    limiter = Limiter(unavailable=True)
    login_app.extensions["rate_limiter"] = limiter
    response = client.post(
        "/login",
        data={"username": "viewer", "password": "a-test-password", "csrf_token": token},
        headers={"X-Forwarded-For": "8.8.8.8"},
    )
    assert response.status_code == 503
    assert limiter.calls[0][1] == "127.0.0.1"


def test_dashboard_service_key_stays_server_side(login_app, user, monkeypatch):
    import httpx

    def upstream(method, url, **kwargs):
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")
        return httpx.Response(200, json={"movies": 0}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", upstream)
    client = login_app.test_client()
    login(client)
    assert client.get("/api/stats").status_code == 200
    assert "A-service-key" not in client.get("/").text


def test_real_atomic_redis_counter_is_shared_and_expires():
    import fakeredis

    from cinegraph.shared.rate_limit import RedisRateLimiter

    redis = fakeredis.FakeRedis()
    first = RedisRateLimiter("redis://unused", client=redis)
    second = RedisRateLimiter("redis://unused", client=redis)
    assert first.allow("test", "same-user", 2, 60)
    assert second.allow("test", "same-user", 2, 60)
    assert not first.allow("test", "same-user", 2, 60)
    key = redis.keys()[0]
    assert 0 < redis.ttl(key) <= 60
    redis.delete(key)
    assert second.allow("test", "same-user", 2, 60)


def test_production_session_cookie_and_csrf_origin(secure_env, user):
    from cinegraph.dashboard.app import create_app

    app = create_app({"TESTING": True})
    app.extensions["rate_limiter"] = Limiter()
    client = app.test_client()
    base = secure_env["DASHBOARD_ORIGIN"]
    response = client.get("/login", base_url=base)
    assert "Secure" in response.headers["Set-Cookie"]
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    response = client.post(
        "/login",
        base_url=base,
        data={"username": "viewer", "password": "a-test-password", "csrf_token": token},
        headers={"Origin": "https://evil.test"},
    )
    assert response.status_code == 400


def test_bad_credentials_dont_create_authenticated_session(login_app, user):
    client = login_app.test_client()
    assert login(client, password="incorrect").status_code == 401
    assert client.get("/api/stats").status_code == 401


def test_session_rotates_after_login_and_rejects_old_cookie(login_app, user):
    client = login_app.test_client()
    token = csrf(client)
    old_cookie = client.get_cookie("cinegraph_session").value
    response = client.post(
        "/login", data={"username": "viewer", "password": "a-test-password", "csrf_token": token}
    )
    assert response.status_code == 302
    assert client.get_cookie("cinegraph_session").value != old_cookie
    attacker = login_app.test_client()
    attacker.set_cookie("cinegraph_session", old_cookie)
    assert attacker.get("/api/stats").status_code == 401


def test_unknown_environment_rejected(monkeypatch):
    from cinegraph.shared.runtime import validate_runtime

    monkeypatch.setenv("CINEGRAPH_ENV", "prodution")
    with pytest.raises(ValueError, match="CINEGRAPH_ENV"):
        validate_runtime()


@pytest.mark.parametrize(
    "key,value",
    [
        ("DATABASE_URL", "postgresql://cinegraph:abc@postgres/cinegraph"),
        ("DATABASE_URL", "postgresql://cinegraph:cinegraph-local-password@postgres/cinegraph"),
        ("REDIS_URL", "redis://redis:6379/0"),
    ],
)
def test_production_rejects_weak_database_credentials(secure_env, monkeypatch, key, value):
    from cinegraph.shared.runtime import validate_runtime

    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        validate_runtime()


def test_catalog_login_is_rate_limited(secure_env, monkeypatch):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from cinegraph.shared.security import CatalogLoginThrottle

    middleware = CatalogLoginThrottle(lambda request: HttpResponse("signed in"))
    middleware.limiter = Limiter(False)
    request = RequestFactory().post(
        "/admin/login/", {"username": "viewer", "password": "secret"}, HTTP_X_FORWARDED_FOR="spoofed"
    )
    assert middleware(request).status_code == 429
    assert middleware.limiter.calls[0][1] == "127.0.0.1"


def test_unicode_csrf_token_is_rejected_without_server_error(login_app):
    client = login_app.test_client()
    csrf(client)
    assert client.post("/login", data={"csrf_token": "☃"}).status_code == 400


@pytest.mark.asyncio
async def test_api_body_timeout_denies_before_endpoint(secure_env, monkeypatch):
    from types import SimpleNamespace

    from cinegraph.shared.runtime import validate_runtime
    from cinegraph.shared.security import APISecurityMiddleware

    called = False

    async def endpoint(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        raise TimeoutError

    messages = []

    async def send(message):
        messages.append(message)

    owner = SimpleNamespace(state=SimpleNamespace(rate_limiter=Limiter()))
    middleware = APISecurityMiddleware(endpoint, owner, validate_runtime())
    scope = {
        "type": "http",
        "path": "/secret",
        "headers": [(b"authorization", f"Bearer {secure_env['CINEGRAPH_API_KEY']}".encode())],
    }
    await middleware(scope, receive, send)
    assert not called
    assert messages[0]["status"] == 408


def test_live_redis_atomic_counter_if_configured():
    import os
    import uuid

    if not os.getenv("CINEGRAPH_TEST_REDIS_URL"):
        pytest.skip("Set CINEGRAPH_TEST_REDIS_URL for live Redis verification")
    from cinegraph.shared.rate_limit import RedisRateLimiter

    limiter = RedisRateLimiter(os.environ["CINEGRAPH_TEST_REDIS_URL"])
    other = RedisRateLimiter(os.environ["CINEGRAPH_TEST_REDIS_URL"])
    identity = uuid.uuid4().hex
    try:
        assert limiter.ping()
        assert limiter.allow("integration-test", identity, 2, 2)
        assert other.allow("integration-test", identity, 2, 2)
        assert not limiter.allow("integration-test", identity, 2, 2)
    finally:
        limiter.close()
        other.close()


def test_production_liveness_allows_loopback_probe_host(secure_env):
    from cinegraph.dashboard.app import create_app

    app = create_app({"TESTING": True})
    client = app.test_client()
    assert client.get("/live", base_url="http://127.0.0.1:5000").status_code == 200
    assert client.get("/live", base_url="http://attacker.invalid").status_code == 400


def test_nonstaff_cannot_read_global_analytics(login_app, user):
    client = login_app.test_client()
    assert login(client).status_code == 302
    assert client.get("/api/analytics").status_code == 403
    assert client.get("/api/analytics.csv").status_code == 403
    assert 'id="activity"' not in client.get("/").text


def test_staff_can_view_global_analytics(login_app, user, monkeypatch):
    import httpx

    user.is_staff = True
    user.save()

    def upstream(method, url, **kwargs):
        return httpx.Response(200, json={"daily": [], "totals": {}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", upstream)
    client = login_app.test_client()
    assert login(client).status_code == 302
    assert client.get("/api/analytics").status_code == 200
    assert 'id="activity"' in client.get("/").text


@pytest.mark.parametrize("trusted,expected", [(False, "127.0.0.1"), (True, "203.0.113.9")])
def test_catalog_client_ip_requires_explicit_proxy_trust(secure_env, monkeypatch, trusted, expected):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from cinegraph.shared.security import CatalogLoginThrottle

    monkeypatch.setenv("DJANGO_TRUST_PROXY", str(trusted).lower())
    middleware = CatalogLoginThrottle(lambda request: HttpResponse("ok"))
    middleware.limiter = Limiter()
    request = RequestFactory().post(
        "/admin/login/", {"username": "viewer"}, HTTP_X_FORWARDED_FOR="203.0.113.9"
    )
    middleware(request)
    assert middleware.limiter.calls[0][1] == expected


@pytest.mark.parametrize("forwarded", ["spoofed", "203.0.113.9, 198.51.100.1", "203.0.113.9:80"])
def test_catalog_proxy_rejects_malformed_or_multiple_client_ips(secure_env, monkeypatch, forwarded):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from cinegraph.shared.security import CatalogLoginThrottle

    monkeypatch.setenv("DJANGO_TRUST_PROXY", "true")
    middleware = CatalogLoginThrottle(lambda request: HttpResponse("ok"))
    middleware.limiter = Limiter()
    middleware(RequestFactory().post("/admin/login/", {"username": "viewer"}, HTTP_X_FORWARDED_FOR=forwarded))
    assert middleware.limiter.calls[0][1] == "127.0.0.1"


def test_trusted_dashboard_proxy_separates_client_rate_budgets(login_app, monkeypatch):
    from cinegraph.dashboard.app import create_app

    monkeypatch.setenv("DJANGO_TRUST_PROXY", "true")
    app = create_app({"TESTING": True})
    limiter = Limiter(False)
    app.extensions["rate_limiter"] = limiter
    for address in ["203.0.113.9", "198.51.100.7"]:
        client = app.test_client()
        token = csrf(client)
        response = client.post(
            "/login",
            data={"username": "viewer", "password": "wrong", "csrf_token": token},
            headers={"X-Forwarded-For": address},
        )
        assert response.status_code == 429
    assert [call[1] for call in limiter.calls if call[0] == "login-ip"] == ["203.0.113.9", "198.51.100.7"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("DATABASE_URL", "postgresql://user:aaaaaaaaaaaaaaaa@db/catalog"),
        ("REDIS_URL", "redis://:aaaaaaaaaaaaaaaa@redis/0"),
        ("DATABASE_URL", "postgresql://user:%61%62%63%64%65%66@db/catalog"),
        ("REDIS_URL", "redis://:%61%62%63%64%65%66@redis/0"),
    ],
)
def test_url_password_strength_checks_decoded_secret(secure_env, monkeypatch, key, value):
    from cinegraph.shared.runtime import validate_runtime

    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        validate_runtime()
