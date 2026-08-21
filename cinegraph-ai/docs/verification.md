# GraphIntel AI — Verification record

Verified locally on 2026-09-20 with Python 3.12, Docker, PostgreSQL 16,
Neo4j 5.26 and Redis 7. This records executed checks, not a cloud certification.

| Check | Actual result |
| --- | --- |
| Full suite with real PostgreSQL, Neo4j and Redis | 172 passed |
| Ruff and Django migration drift | Passed; no model changes awaiting migrations |
| Python dependency audit | No known vulnerabilities |
| Docker build | Passed; Python 3.12.14 on Wolfi, collected admin static files |
| Final complete application image scan | Zero HIGH/CRITICAL findings across OS and Python packages |
| Final container runtime smoke and browser workflow | Passed, including analytics, login/logout and CSV export; zero browser errors |
| Caddy configuration validation | Passed |
| Production-mode isolated Compose | Read-only app containers, private authenticated dependencies, readiness and bearer authentication exercised |
| Redis outage | API liveness remained 200; readiness and protected requests returned 503 |
| PostgreSQL outage and recovery | Liveness 200, readiness 503 during outage; readiness 200 and healthy worker heartbeat after restart, without a worker container restart |
| Backup and restore | Custom PostgreSQL dump with SHA-256 restored to a new database; 24 catalog records verified |
| Concurrent local API check | 100 requests, concurrency 8, zero errors; p50 211 ms, p95 1,156 ms, approximately 26 requests/second |
| Kubernetes and CI YAML parsing | Passed; no actual cluster rollout or remote workflow run |

The suite covers session rotation/revocation, CSRF, permissions, Redis limits,
strict production settings, SQL rollback, concurrent outbox processing,
dead-letter isolation and recovery, worker database reconnection, graph updates
and deletion, indexed retrieval beyond 1,000 records, keyset pagination, provider
limits, citations, and an actual MCP stdio subprocess. Readiness checks graph
indexes and database migration state. Production initialization creates no sample
data and leaves projection to the worker.

Authenticated browser automation exercised 24 movie cards, details,
recommendations, title search, sourced chat, SVG graph, analytics and CSV
export. A 390-pixel mobile viewport had no horizontal overflow. No JavaScript
errors occurred. Desktop and mobile screenshots were inspected.

The load check is a small local smoke test, not a capacity or availability claim.
The deterministic evaluator has only two retrieval queries and two recommendation
cases (both scores 1.0); it does not establish production model quality. No paid
LLM request was made; provider behavior uses controlled HTTP fixtures in tests.

The production Compose check used isolated local dependencies and test host ports.
Public DNS, live TLS issuance, managed database failover, Kubernetes enforcement,
cloud provisioning and remote GitHub release execution remain environment-specific
rollout work. Kubernetes resource discovery was unavailable on the configured
cluster. Single-host Compose does not provide high availability.

Test warnings are upstream Starlette/httpx and AnyIO deprecations and a local
Django static-directory warning before collectstatic; container static collection
succeeds. See [image scan](image-scan.md), [deployment](deployment.md) and
[operations](operations.md) for release controls and runbooks.

## GraphIntel AI terminology update — 2026-09-20

The public project name, dashboard copy, API/MCP/admin titles and documentation
were aligned to data analytics and conversational intelligence. Existing package,
CLI, database and deployment identifiers retain `cinegraph` for compatibility.
The affected dashboard/API/MCP/catalog suite passed 79 tests; Ruff, JavaScript
syntax and documentation links passed. Authenticated desktop/mobile browser
checks verified the revised text with no JavaScript errors or horizontal overflow.
The earlier full-suite and image-scan records above describe the hardening build;
this terminology-only change does not introduce new framework integrations.
