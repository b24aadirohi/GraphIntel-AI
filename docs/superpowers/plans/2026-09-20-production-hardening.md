# CineGraph production hardening implementation plan

User requests production-grade evolution of the existing app and has instructed no further clarification questions. Execute using writing-plans, test-driven-development, subagent-driven-development and verification-before-completion workflows. Keep existing local data and other projects intact.

## Target architecture and boundaries
- Keep Django/Postgres authoritative catalog, Flask UI, FastAPI/Neo4j discovery, and MCP.
- Development remains localhost-capable. CINEGRAPH_ENV=production fails closed on missing/weak credentials, debug flags, missing HTTPS origins and missing Redis. Never claim a configuration file proves a production deployment.
- Authenticated Flask dashboard uses existing Django users; server-side sessions/revocation, CSRF and login throttling. API has private bearer service key, never browser-exposed. Rate limits use Redis and deny requests if unavailable in protected mode. Anonymous probes reveal no data.
- Ordered delivery per movie, bounded retries, dead-letter recovery, no global poison-event blockage. Explicit operational status and worker heartbeat.
- Neo4j indexed candidate retrieval instead of first1000 scans, deterministic pagination, bounded recommendation corpus + cached ML transform; hosted input/output limits and safe failure modes.
- Structured request logs, request IDs, protected metrics; readiness distinct from liveness; graceful process exit.
- Production TLS ingress, private databases, read-only dropped-capability containers, resource limits, hardened Kubernetes network/RBAC configuration and safe migrations; backup/restore and monitoring runbooks.

## Work packages
1. Security: strict runtime environment checks, Flask login/session/CSRF, bearer API middleware, shared Redis rate limiter, Django production settings, meaningful tests (red first).
2. Reliability: migration for retries/dead letters, per-movie ordered nonblocking work, locked worker claims, retry command, heartbeat and health, bounded retention and data recovery commands; integration regressions.
3. Discovery: graph fulltext index plus keyset pagination, relationship candidate retrieval, cache invalidation, provider output/response size guards, typed API responses and lifecycle/probe integration; backwards-compatible route response items and UI pagination.
4. Operations: production Compose/TLS, Kubernetes probes/security/resources/network policy, JSON logs/metrics, CI audit and scans, backup and restore scripts, docs and load/smoke verification.

## Ownership and interfaces
- Security owns shared/security.py, shared/rate_limit.py, shared/runtime.py, dashboard/**, catalog/settings.py and new security tests. Provide install_api_security(app) called by API agent. Service auth CINEGRAPH_API_KEY; server session DJANGO_SECRET_KEY; CINEGRAPH_REQUIRE_AUTH defaults true in production and may be true in development. REDIS_URL required when authenticated. DASHBOARD_ORIGIN and CATALOG_ORIGIN HTTPS in production. API upstream header Bearer is server-only. Health endpoints excluded but metrics protected.
- Reliability owns catalog/** EXCEPT settings.py, its tests and migrations. Expose projection_status() and worker health command; mutations and delete delivery remain consistent. Root operations integration may use published functions.
- Discovery owns shared/{graph,recommendations,rag,config}.py, api/**, MCP/** and their tests. Calls security install hook and root observability install hook. API /live dependency-free; /ready checks dependencies; /health compatibility alias to readiness. Existing endpoint shapes remain compatible, movies adds cursor pagination.
- Root owns dependencies, CI, deployment, scripts, shared/observability.py, cross-service tests and docs. All changes reversible and local; no cloud provisioning/publishing.

## Acceptance checks
- Existing regression suite and new auth/config/rate-limit/queue/search tests pass with real PostgreSQL, Neo4j and Redis.
- Production startup refuses insecure configuration; authenticated browser login/logout, CSRF and private API access tested.
- Dead-lettered movie cannot stall other movies or let older updates overwrite newer updates; retries observable and recoverable.
- Queries beyond original first1000 cap retrieve correctly; no per-request full-catalog ML rebuild; pagination works.
- Full production-mode smoke against local isolated test configuration, browser workflow, image build and modest concurrent-load report.
- Configuration schema, migration check, lint, dependency audit and documented untested cloud/live-TLS limitations.

## Progress
- [x] Security
- [x] Reliability
- [x] Discovery
- [x] Operations
- [x] Cross-service verification and review

Verification: 172 tests passed with real PostgreSQL, Neo4j and Redis; authenticated
browser workflow passed; final Wolfi application image has zero HIGH/CRITICAL
scanner findings. Isolated production Compose probes/authentication, Redis and
PostgreSQL outage behavior, worker recovery, and backup/restore exercised locally.
Cloud rollout, public TLS issuance and remote GitHub workflow execution remain
environment-specific deployment work. See cinegraph-ai/docs/verification.md.
