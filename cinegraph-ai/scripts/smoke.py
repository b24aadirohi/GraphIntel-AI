"""Exercise the running stack without adding catalog data or requiring an LLM key."""
import argparse
import json
import os
from urllib.request import Request, urlopen


def fetch(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if os.getenv("CINEGRAPH_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["CINEGRAPH_API_KEY"]
    request = Request(base + path, data=data, headers=headers)
    with urlopen(request, timeout=45) as response:
        body = response.read()
        return json.loads(body) if "application/json" in response.headers.get("Content-Type", "") else body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8100")
    parser.add_argument("--dashboard", default="http://localhost:5100")
    parser.add_argument("--catalog", default="http://localhost:8101")
    args = parser.parse_args()
    for base, path in [(args.api, "/health"), (args.dashboard, "/health"), (args.catalog, "/health/")]:
        assert fetch(base, path), f"Empty health response: {base}"
    stats = fetch(args.api, "/stats")
    assert stats["movies"] >= 20, stats
    movies = fetch(args.api, "/movies?limit=5")["items"]
    assert len(movies) == 5
    movie = fetch(args.api, "/movies/" + movies[0]["id"])
    assert movie["title"] == movies[0]["title"]
    recommendations = fetch(args.api, "/recommendations/" + movie["id"])["items"]
    assert recommendations and all(item["id"] != movie["id"] for item in recommendations)
    graph = fetch(args.api, "/graph?limit=10")
    assert graph["nodes"] and graph["links"]
    chat = fetch(args.api, "/chat", {"question": movie["title"]})
    assert chat["sources"] and chat["answer"], chat
    report = fetch(args.api, "/analytics")
    assert report["totals"]["search"] >= 1 and report["totals"]["chat"] >= 1, report
    assert b"GraphIntel" in fetch(args.dashboard, "/")
    assert b"csrfmiddlewaretoken" in fetch(args.catalog, "/admin/login/")
    print(json.dumps({"status": "passed", "catalog_movies": stats["movies"], "chat_mode": chat["mode"], "checks": ["three service health checks", "catalog", "detail", "recommendations", "graph", "sourced chat", "SQL analytics", "dashboard", "staff login"]}, indent=2))


if __name__ == "__main__":
    main()
