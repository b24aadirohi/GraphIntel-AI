"""Django-backed browser sessions without exposing the service credential."""

import hmac
import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from flask import g, jsonify, redirect, render_template, request

from cinegraph.shared.rate_limit import RateLimitUnavailable, RedisRateLimiter
from cinegraph.shared.runtime import flag
from cinegraph.shared.security import SanitizeProxyClientIP

COOKIE = "cinegraph_session"
PUBLIC = {"/login", "/live", "/ready", "/health"}


def install_dashboard_auth(app, runtime):
    app.extensions["security_runtime"] = runtime
    if flag("DJANGO_TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = SanitizeProxyClientIP(
            ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)
        )
    if runtime.production:

        @app.before_request
        def require_https():
            if not request.is_secure and request.path not in {"/live", "/ready", "/health"}:
                return redirect(runtime.dashboard_origin + request.full_path.rstrip("?"), code=308)
            return None

        app.config["TRUSTED_HOSTS"] = [
            host.strip()
            for host in os.getenv(
                "DASHBOARD_ALLOWED_HOSTS",
                f"{urlsplit(runtime.dashboard_origin).hostname},localhost,127.0.0.1",
            ).split(",")
            if host.strip()
        ]
        if not app.config["TRUSTED_HOSTS"] or "*" in app.config["TRUSTED_HOSTS"]:
            raise ValueError("DASHBOARD_ALLOWED_HOSTS must name specific hosts")
    if not runtime.require_auth:

        @app.context_processor
        def anonymous_context():
            return {"auth_required": False, "csrf_token": "", "can_view_analytics": True}

        return

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinegraph.catalog.settings")
    django.setup()
    from django.contrib.auth import authenticate, get_user_model
    from django.contrib.sessions.backends.db import SessionStore
    from django.db import DatabaseError, close_old_connections
    from django.utils import timezone

    app.extensions["rate_limiter"] = RedisRateLimiter(runtime.redis_url)

    @app.errorhandler(DatabaseError)
    def database_unavailable(error):
        return jsonify(error="Account service unavailable. Try again shortly."), 503

    @app.errorhandler(RateLimitUnavailable)
    def protection_unavailable(error):
        return jsonify(error="Request protection unavailable. Try again shortly."), 503

    @app.before_request
    def session_and_csrf():
        if request.path.startswith("/static/") or request.path in {"/live", "/ready", "/health"}:
            return None
        close_old_connections()
        g.account_session = SessionStore(session_key=request.cookies.get(COOKIE))
        g.account_user = None
        user_id = g.account_session.get("dashboard_user_id")
        if user_id:
            user = get_user_model().objects.filter(pk=user_id).first()
            saved_hash = g.account_session.get("dashboard_auth_hash", "")
            if user and user.is_active and hmac.compare_digest(saved_hash, user.get_session_auth_hash()):
                g.account_user = user
            else:
                g.account_session.flush()
        if request.path not in PUBLIC and not g.account_user:
            if request.path.startswith("/api/") or request.path == "/metrics":
                return jsonify(error="Sign in to continue."), 401
            return redirect("/login")
        if request.path in {"/api/analytics", "/api/analytics.csv"} and not g.account_user.is_staff:
            return jsonify(error="Staff access is required to view activity reports."), 403
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected = g.account_session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
            origin = request.headers.get("Origin")
            allowed_origin = runtime.dashboard_origin or request.host_url.rstrip("/")
            if (
                not expected
                or not isinstance(supplied, str)
                or not hmac.compare_digest(expected.encode(), supplied.encode())
                or (origin and origin != allowed_origin)
            ):
                return jsonify(error="The form expired or came from another site. Reload and try again."), 400
        return None

    @app.context_processor
    def account_context():
        session = getattr(g, "account_session", None)
        return {
            "auth_required": True,
            "csrf_token": session.get("csrf_token", "") if session else "",
            "can_view_analytics": bool(getattr(g, "account_user", None) and g.account_user.is_staff),
        }

    @app.after_request
    def persist_session(response):
        session = getattr(g, "account_session", None)
        response.headers["Cache-Control"] = "no-store"
        if session is not None:
            try:
                if getattr(g, "delete_account_cookie", False) or not session:
                    response.delete_cookie(
                        COOKIE, path="/", secure=runtime.production, httponly=True, samesite="Lax"
                    )
                elif session.modified and response.status_code < 500:
                    session.save()
                    response.set_cookie(
                        COOKIE,
                        session.session_key,
                        max_age=session.get_expiry_age(),
                        secure=runtime.production,
                        httponly=True,
                        samesite="Lax",
                        path="/",
                    )
            except DatabaseError:
                response = jsonify(error="Account service unavailable. Try again shortly.")
                response.status_code = 503
                response.headers["Cache-Control"] = "no-store"
        return response

    @app.teardown_request
    def close_account_connection(error):
        close_old_connections()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        session = g.account_session
        if request.method == "GET":
            if g.account_user:
                return redirect("/")
            if not session.get("csrf_token"):
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.set_expiry(timezone.now() + timedelta(minutes=30))
            return render_template("login.html", error=None)
        username = request.form.get("username", "").strip()[:150]
        password = request.form.get("password", "")
        limiter = app.extensions["rate_limiter"]
        ip_allowed = limiter.allow("login-ip", request.remote_addr or "unknown", 30, 900)
        user_allowed = limiter.allow("login-user", username.casefold(), 10, 900)
        if not ip_allowed or not user_allowed:
            return (
                render_template("login.html", error="Too many sign-in attempts. Try again in 15 minutes."),
                429,
                {"Retry-After": "900"},
            )
        user = (
            authenticate(username=username, password=password) if username and len(password) <= 4096 else None
        )
        if not user or not user.is_active:
            return render_template("login.html", error="The username or password is incorrect."), 401
        session.flush()
        session["dashboard_user_id"] = str(user.pk)
        session["dashboard_auth_hash"] = user.get_session_auth_hash()
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.set_expiry(timezone.now() + timedelta(hours=8))
        return redirect("/")

    @app.post("/logout")
    def logout():
        g.account_session.flush()
        g.delete_account_cookie = True
        return redirect("/login")
