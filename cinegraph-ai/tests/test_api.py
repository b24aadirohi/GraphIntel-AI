from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from cinegraph.api.app import create_app
from cinegraph.shared.evaluate import FixtureRepository


class Repository(FixtureRepository):
    def search(self, q, limit):
        return [m for m in self.movies if q.lower() in m["title"].lower()][:limit]

    def search_page(self, q, limit, cursor=None):
        return {"items": self.search(q, limit), "next_cursor": None, "has_more": False}

    def graph(self, limit):
        return {"nodes": [], "links": []}

    def stats(self):
        return {"movies": len(self.movies), "people": 0, "genres": 0}


@pytest.fixture
def client(monkeypatch):
    from cinegraph.catalog import analytics
    monkeypatch.setattr(analytics, "record_event", lambda kind: None)
    monkeypatch.setattr(analytics, "report", lambda start, end: {"daily": [], "totals": {}})
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    repo = Repository([{"id": "one", "title": "Orbit", "summary": "space planet",
                        "released": 2020, "genres": ["Sci-Fi"], "cast": [], "directors": []}])
    with TestClient(create_app(repo)) as test_client:
        yield test_client


def test_routes(client):
    assert client.get("/movies?q=orbit").json()["items"][0]["id"] == "one"
    assert client.get("/movies/one").json()["title"] == "Orbit"
    assert client.get("/movies/missing").status_code == 404
    assert client.get("/recommendations/missing").status_code == 404
    assert client.get("/recommendations/one").json() == {"items": []}
    assert client.get("/graph").json() == {"nodes": [], "links": []}
    assert client.get("/stats").json()["movies"] == 1
    assert client.get("/analytics").status_code == 200
    assert client.post("/chat", json={"question": "space"}).json()["mode"] == "evidence"


def test_validation(client):
    for path in ("/movies?limit=101", "/graph?limit=0", "/recommendations/one?limit=21",
                 "/analytics?start=2026-09-20&end=2026-01-01", "/analytics?start=invalid"):
        assert client.get(path).status_code == 422
    assert client.post("/chat", json={"question": " "}).status_code == 422
    assert client.post("/chat", json={"question": "x" * 2001}).status_code == 422


def test_graph_unavailable(client, monkeypatch):
    def fail(*args):
        raise ServiceUnavailable("internal-secret")
    monkeypatch.setattr(client.app.state.repository, "search", fail)
    response = client.get("/movies")
    assert response.status_code == 503
    assert "internal-secret" not in response.text


def test_sql_health_unavailable(client, monkeypatch):
    from django.db import OperationalError

    def fail(*args):
        raise OperationalError("internal connection details")

    monkeypatch.setattr(client.app.state.repository, "health", lambda: None, raising=False)
    monkeypatch.setattr("cinegraph.api.app.connection", SimpleNamespace(cursor=fail))
    response = client.get("/health")
    assert response.status_code == 503
    assert "internal connection details" not in response.text


def test_hosted_error_not_reported_as_evidence(client, monkeypatch):
    from cinegraph.shared.rag import ProviderError

    def fail(*args):
        raise ProviderError("Configured LLM provider failed")

    monkeypatch.setattr("cinegraph.api.app.chat", fail)
    response = client.post("/chat", json={"question": "space"})
    assert response.status_code == 502
    assert "provider failed" in response.json()["detail"]


def test_liveness_does_not_check_dependencies(client, monkeypatch):
    def fail(*args):
        raise AssertionError("Liveness touched a dependency")
    monkeypatch.setattr(client.app.state.repository, "health", fail, raising=False)
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_cursor_is_422(client, monkeypatch):
    def fail(*args):
        raise ValueError("Invalid pagination cursor")
    monkeypatch.setattr(client.app.state.repository, "search_page", fail)
    response = client.get("/movies?cursor=invalid")
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid pagination cursor"
