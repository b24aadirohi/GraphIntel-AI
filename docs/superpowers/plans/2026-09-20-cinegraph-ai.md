# CineGraph AI Implementation Plan

> For agentic workers: implement the approved design using subagent-driven-development and run real integration checks.

**Goal:** Deliver a runnable three-framework movie analytics and graph RAG portfolio application.
**Architecture:** Django/PostgreSQL catalog with transactional outbox projects to Neo4j. FastAPI and MCP use shared graph/recommendation/RAG code. Flask calls FastAPI.
**Tech Stack:** Python 3.12, Django 5.2, Flask 3, FastAPI, Neo4j 5.26, PostgreSQL 16, MCP Python SDK 1.x, scikit-learn, Docker.

## Global Constraints
- New code lives in cinegraph-ai; preserve original examples.
- No API keys required for evidence-only mode. Never represent evidence-only mode as LLM generation.
- Local services bind loopback; no cloud resources or external publication.
- Parameterized queries, validated input, staff-only catalog mutation, bounded context and results.
- User approved design and requests no further questions. Resolve routine choices autonomously.

## Task 1: Catalog and SQL projection source
- [x] Create Django settings, models, admin, migrations, commands, and tests.
- [x] Movie fields: id string, title string, released integer, summary string, genres list of strings, cast list of strings, directors list of strings.
- [x] Shared graph interface: GraphRepository.upsert_movie(movie: dict), delete_movie(movie_id: str), ensure_schema(), close().
- [x] Use SQL transaction + outbox; worker locks pending work and retries failures without losing updates.
- [x] Seed packaged JSON via manage.py seed; sync via manage.py sync_graph [--watch].
- [x] Analytics API integration uses catalog.analytics.record_event(kind: str), report(start: date|None, end: date|None) -> dict; daily aggregation command.
- [x] Verify seed idempotence, admin protection, update/delete projection and retry with tests.

## Task 2: Discovery, ML, RAG and MCP
- [x] Implement shared config and Neo4j repository with ensure_schema, upsert_movie, delete_movie, search(q, limit), get_movie(id), list_movies(limit), graph(limit), stats, close.
- [x] JSON movie contract matches Task 1. GET /movies?q=&limit=, GET /movies/{id}, GET /graph?limit=, GET /recommendations/{id}?limit=, GET /stats, GET /analytics?start=&end=, POST /chat {question}, GET /health.
- [x] Responses: movies {items: [...]}; graph {nodes:[{id,label,type}],links:[{source,target,type}]}; recommendations {items:[movie fields + score + explanation]}; stats {movies,people,genres}; analytics {daily:[{date,search,recommendation,chat}],totals:{search,recommendation,chat}}; chat {answer,mode,sources:[{id,title,summary}]}.
- [x] ML: TF-IDF + graph overlap; test ranking with deterministic fixtures and evaluate retrieval.
- [x] RAG retrieves bounded evidence, validates citations for optional hosted adapter, exposes explicit evidence mode.
- [x] MCP stdio exposes search_movies, get_movie, recommend_movies; integration test real subprocess protocol.
- [x] Neo4j integration checks schema/upsert/search/delete against test database.

## Task 3: Flask dashboard
- [x] Implement Flask factory cinegraph.dashboard.app:create_app serving templates/static resources, with HTTP proxy routes to API.
- [x] Provide catalog search, detail/recommendations, graph, analytics filters/charts, chat sources and CSV export matching filters.
- [x] Use same-origin proxy; API_BASE_URL defaults http://localhost:8000; timeouts and graceful failure UI.
- [x] Test dashboard response, upstream failures, input handling, CSV correctness and escaping.

## Task 4: Packaging and delivery
- [x] Create pyproject, reproducible dependency lock, Docker image and Compose database health checks.
- [x] One-shot init runs migration + seed + sync. API/dashboard/catalog/worker wait for successful init.
- [x] Add Kubernetes application manifests with external database configuration and migration job.
- [x] Add CI: lint, tests with live databases, build image.
- [x] Write PowerShell/POSIX setup, architecture, MCP configuration, cloud guide and honest job requirement matrix.
- [x] Run unit and integration tests, start Compose, smoke all services, and record actual outcomes.

## Verification commands
```sh
cd cinegraph-ai
uv sync --extra dev
uv run ruff check .
uv run pytest
# Database-backed suite, with connection variables set:
CINEGRAPH_INTEGRATION=1 uv run pytest
# Full-stack acceptance:
docker compose up --build -d
curl --fail http://localhost:8100/health
curl --fail http://localhost:5100/health
curl --fail http://localhost:8101/health/
```

## Completion evidence

Implemented and reviewed on 2026-09-20. Full real-database suite: 93 passed.
Container build and live browser/service smoke passed. See
`cinegraph-ai/docs/verification.md` for outcomes and deployment limitations.
Default external ports changed to avoid other active local applications.

Review resolved seed overwrites, SQL/graph bounds, canonical movie IDs, provider
timeout ordering, sample-data labelling and citation button identifiers.
No remaining material findings in the scoped re-review. Work remains local.
