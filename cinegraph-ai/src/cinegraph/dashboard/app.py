"""Same-origin, bounded gateway to the discovery API."""

import csv
import io
import os
import re
from datetime import date
from urllib.parse import quote

import httpx
from flask import Flask, Response, g, jsonify, render_template, request

from cinegraph.dashboard.auth import install_dashboard_auth
from cinegraph.shared.observability import install_flask_observability
from cinegraph.shared.runtime import validate_runtime


class InputError(ValueError):
    """Invalid browser input."""


def create_app(config=None):
    runtime = validate_runtime()
    app = Flask(__name__)
    app.config.from_mapping(
        API_BASE_URL=os.getenv("API_BASE_URL", "http://localhost:8000"),
        API_TIMEOUT=35.0,
        CATALOG_URL=os.getenv("CATALOG_URL", "http://localhost:8101/admin/"),
        MAX_CONTENT_LENGTH=16384,
    )
    if config:
        app.config.update(config)

    install_flask_observability(app)
    install_dashboard_auth(app, runtime)

    def upstream(path, *, params=None, payload=None):
        try:
            response = httpx.request(
                "POST" if payload is not None else "GET",
                app.config["API_BASE_URL"].rstrip("/") + path,
                params=params,
                headers={
                    **({"Authorization": f"Bearer {runtime.api_key}"} if runtime.api_key else {}),
                    **({"X-Request-ID": g.request_id} if getattr(g, "request_id", None) else {}),
                },
                json=payload,
                timeout=app.config["API_TIMEOUT"],
                follow_redirects=False,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            return data
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {"error": "This movie was not found."}, 404
            app.logger.warning("API status failure: %s", exc.response.status_code)
        except (httpx.RequestError, ValueError):
            app.logger.warning("API unavailable or returned invalid data")
        return {"error": "The movie service is unavailable. Try again shortly."}, 502

    def limit(default=24, maximum=100):
        raw = request.args.get("limit", str(default))
        if not raw.isascii() or not raw.isdigit() or len(raw) > 3 or not 1 <= int(raw) <= maximum:
            raise InputError(f"Limit must be between 1 and {maximum}.")
        return int(raw)

    def movie_id(value):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) or value in {".", ".."}:
            raise InputError("Invalid movie identifier.")
        return quote(value, safe="")

    def dates():
        params = {}
        for key in ("start", "end"):
            value = request.args.get(key)
            if value:
                try:
                    parsed = date.fromisoformat(value)
                    if parsed.isoformat() != value:
                        raise ValueError
                except ValueError as exc:
                    raise InputError("Dates must use YYYY-MM-DD.") from exc
                params[key] = value
        if params.get("start", "") > params.get("end", "9999-12-31"):
            raise InputError("Start date must be on or before end date.")
        return params

    @app.errorhandler(InputError)
    def invalid_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="The request is too large."), 413

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        if runtime.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", catalog_url=app.config["CATALOG_URL"])

    @app.get("/live")
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "dashboard"}

    @app.get("/ready")
    def ready():
        if runtime.require_auth:
            from django.db import DatabaseError, close_old_connections, connection

            from cinegraph.shared.rate_limit import RateLimitUnavailable

            try:
                close_old_connections()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                app.extensions["rate_limiter"].ping()
            except (DatabaseError, RateLimitUnavailable):
                return {"status": "unavailable"}, 503
            finally:
                close_old_connections()
        result = upstream("/ready")
        if isinstance(result, tuple):
            return {"status": "unavailable"}, 503
        return {"status": "ok"}

    @app.get("/api/movies")
    def movies():
        query = request.args.get("q", "").strip()
        if len(query) > 200:
            raise InputError("Search must be 200 characters or fewer.")
        params = {"q": query, "limit": limit()}
        cursor = request.args.get("cursor", "")
        if len(cursor) > 2048:
            raise InputError("Invalid pagination cursor.")
        if cursor:
            params["cursor"] = cursor
        return upstream("/movies", params=params)

    @app.get("/api/movies/<identifier>")
    def movie(identifier):
        return upstream("/movies/" + movie_id(identifier))

    @app.get("/api/recommendations/<identifier>")
    def recommendations(identifier):
        return upstream(
            "/recommendations/" + movie_id(identifier),
            params={"limit": limit(6, 20)},
        )

    @app.get("/api/graph")
    def graph():
        return upstream("/graph", params={"limit": limit(30)})

    @app.get("/api/stats")
    def stats():
        return upstream("/stats")

    @app.get("/api/analytics")
    def analytics():
        return upstream("/analytics", params=dates())

    @app.get("/api/analytics.csv")
    def analytics_csv():
        data = upstream("/analytics", params=dates())
        if isinstance(data, tuple):
            return data
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["date", "search", "recommendation", "chat"])
        try:
            for row in data["daily"]:
                # Only canonical dates and numeric counts enter the CSV.
                day = date.fromisoformat(row["date"]).isoformat()
                counts = [int(row.get(key, 0)) for key in ("search", "recommendation", "chat")]
                writer.writerow([day, *counts])
        except (KeyError, TypeError, ValueError):
            return {"error": "The activity report is unavailable. Try again shortly."}, 502
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="cinegraph-activity.csv"'},
        )

    @app.post("/api/chat")
    def chat():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("question"), str):
            raise InputError("Provide a question as text.")
        question = data["question"].strip()
        if not question or len(question) > 2000:
            raise InputError("Questions must contain 1 to 2,000 characters.")
        return upstream("/chat", payload={"question": question})

    return app
