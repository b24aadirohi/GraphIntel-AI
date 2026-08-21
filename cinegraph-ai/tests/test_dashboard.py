"""Dashboard gateway behavior, validation, and export safety."""

import csv
import io

import httpx
import pytest

from cinegraph.dashboard.app import create_app


@pytest.fixture
def client():
    return create_app({"TESTING": True, "API_BASE_URL": "http://test-api:8000"}).test_client()


def stub(monkeypatch, data, status=200):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(status, json=data, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    return calls


def test_dashboard_and_liveness(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Explore connected data" in response.data
    assert "Sample catalog · Fictional films" in response.text
    assert b"https://" not in response.data
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/health").json["status"] == "ok"
    assert client.get("/static/app.js").status_code == 200


def test_search_query_is_forwarded_as_data(client, monkeypatch):
    payload = {"items": [{"id": "m1", "title": "<script>alert(1)</script>"}]}
    calls = stub(monkeypatch, payload)
    response = client.get("/api/movies", query_string={"q": " <script> ", "limit": 4})
    assert response.json == payload
    assert response.content_type == "application/json"
    assert calls[0][1] == "http://test-api:8000/movies"
    assert calls[0][2]["params"] == {"q": "<script>", "limit": 4}
    assert calls[0][2]["timeout"] == 35
    assert calls[0][2]["follow_redirects"] is False
    # The browser renders all upstream strings as text, never markup.
    script = client.get("/static/app.js").text
    assert "innerHTML" not in script
    assert "textContent" in script


@pytest.mark.parametrize(
    "path",
    [
        "/api/movies?limit=0",
        "/api/movies?limit=101",
        "/api/movies?limit=bad",
        "/api/movies?q=" + "x" * 201,
        "/api/movies/%20%20",
        "/api/movies/film%20name",
        "/api/movies/film%3Fname",
        "/api/movies/film%23name",
        "/api/movies/film%25name",
        "/api/movies/" + "x" * 129,
        "/api/movies/..",
        "/api/analytics?start=2026-02-30",
        "/api/analytics?end=20260920",
        "/api/analytics?start=2026-09-20&end=2026-09-01",
        "/api/analytics.csv?start=not-a-date",
        "/api/recommendations/m1?limit=21",
    ],
)
def test_invalid_input_never_reaches_upstream(client, monkeypatch, path):
    calls = stub(monkeypatch, {})
    assert client.get(path).status_code == 400
    assert not calls


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"question": []}, {"question": " "}, {"question": "x" * 2001}]
)
def test_chat_validation(client, monkeypatch, payload):
    calls = stub(monkeypatch, {})
    assert client.post("/api/chat", json=payload).status_code == 400
    assert not calls


def test_chat_proxy(client, monkeypatch):
    calls = stub(monkeypatch, {"answer": "Evidence", "mode": "evidence-only", "sources": []})
    assert client.post("/api/chat", json={"question": " Alien? "}).status_code == 200
    assert calls[0][0] == "POST"
    assert calls[0][2]["json"] == {"question": "Alien?"}


def test_upstream_timeout_is_graceful(client, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("sensitive internal host")

    monkeypatch.setattr(httpx, "request", fail)
    response = client.get("/api/stats")
    assert response.status_code == 502
    assert "unavailable" in response.json["error"]
    assert "sensitive" not in response.text


@pytest.mark.parametrize("status,expected", [(404, 404), (500, 502), (403, 502)])
def test_upstream_status(client, monkeypatch, status, expected):
    stub(monkeypatch, {"detail": "internal"}, status)
    assert client.get("/api/movies/m1").status_code == expected


def test_invalid_upstream_data(client, monkeypatch):
    stub(monkeypatch, [])
    assert client.get("/api/stats").status_code == 502


def test_csv_matches_analytics_filters(client, monkeypatch):
    calls = stub(
        monkeypatch,
        {"daily": [{"date": "2026-09-20", "search": 3, "recommendation": 2, "chat": 1}], "totals": {}},
    )
    filters = {"start": "2026-09-01", "end": "2026-09-20"}
    client.get("/api/analytics", query_string=filters)
    response = client.get("/api/analytics.csv", query_string=filters)
    assert calls[0][2]["params"] == calls[1][2]["params"] == filters
    assert response.status_code == 200
    assert list(csv.reader(io.StringIO(response.text))) == [
        ["date", "search", "recommendation", "chat"],
        ["2026-09-20", "3", "2", "1"],
    ]
    assert "attachment" in response.headers["Content-Disposition"]


def test_csv_rejects_formula_injection(client, monkeypatch):
    stub(monkeypatch, {"daily": [{"date": "=HYPERLINK(bad)", "search": 0}]})
    assert client.get("/api/analytics.csv").status_code == 502


def test_csv_upstream_error(client, monkeypatch):
    stub(monkeypatch, {}, 500)
    assert client.get("/api/analytics.csv").status_code == 502


@pytest.mark.parametrize(
    "identifier,encoded",
    [
        ("custom.film", "custom.film"),
        ("film_1-2026", "film_1-2026"),
        ("x" * 128, "x" * 128),
    ],
)
@pytest.mark.parametrize("resource", ["movies", "recommendations"])
def test_movie_ids_are_quoted_path_segments(client, monkeypatch, identifier, encoded, resource):
    calls = stub(monkeypatch, {"id": identifier})
    response = client.get(f"/api/{resource}/{encoded}")
    assert response.status_code == 200
    assert calls[0][1] == f"http://test-api:8000/{resource}/{encoded}"


def test_browser_allows_upstream_timeout_and_matches_citation_ids(client):
    script = client.get("/static/app.js").text
    assert "controller.abort(), 45000" in script
    assert "`[${source.id}] ${source.title}`" in script


def test_movie_pagination_forwards_bounded_cursor(client, monkeypatch):
    calls = stub(monkeypatch, {"items": [], "next_cursor": None, "has_more": False})
    assert (
        client.get(
            "/api/movies", query_string={"q": "space", "cursor": "opaque-page", "limit": 10}
        ).status_code
        == 200
    )
    assert calls[0][2]["params"]["cursor"] == "opaque-page"
    assert client.get("/api/movies", query_string={"cursor": "x" * 2049}).status_code == 400


def test_dashboard_readiness_checks_api_and_returns_no_details(client, monkeypatch):
    stub(monkeypatch, {"status": "ok", "secret": "internal"})
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    stub(monkeypatch, {}, status=503)
    assert client.get("/ready").status_code == 503


@pytest.mark.parametrize("value", ["²", "1" * 5000])
def test_malformed_numeric_limit_is_rejected(client, value):
    assert client.get("/api/movies", query_string={"limit": value}).status_code == 400
