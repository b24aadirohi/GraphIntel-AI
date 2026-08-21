# GraphIntel AI — Operations and recovery

## Health and visibility

`/live` is dependency-free; `/ready` checks dependencies. Django uses trailing
slashes. Worker readiness is `python manage.py worker_health`, based on a durable
heartbeat and default 90-second freshness. Kubernetes liveness tolerates 180s
for worker recovery; readiness removes unavailable web replicas without turning
a database outage into a liveness restart loop.

FastAPI's protected `/operations` returns backlog, dead-letter count, oldest
pending age and latest running heartbeat. Protected `/metrics` exposes request
counts and latency histograms. Scrape configuration and example alerts are in
`deploy/monitoring/`; mount the service key as the indicated secret file. A
single API process runs per replica, keeping metrics accounting correct. Discover
and scrape every API pod separately in Kubernetes rather than scraping only a
load-balanced service endpoint. Schedule an authenticated `/operations` check
and alert on deadletters > 0 or a growing backlog/old heartbeat.

Suggested initial objectives: >99.9% successful non-chat requests, p95 below 1s,
projection backlog younger than 60s, no unrecovered deadletters. These are
operational targets, not measured availability guarantees. Adjust based on real
traffic and provider behavior.

## Queue recovery

Each movie has an independent ordering barrier. Failed projection retries use
bounded exponential delay and five attempts before dead-lettering. Other movies
continue. Later events for a dead-lettered movie wait until the earlier event is
recovered. Nothing is silently discarded.

```sh
docker compose exec catalog python manage.py retry_outbox --id 123
# Or retry failed events for one movie:
docker compose exec catalog python manage.py retry_outbox --movie-id your.movie.id
docker compose exec catalog python manage.py worker_health
```

Inspect outbox error codes/status in Django admin and fix the actual connection
or payload problem before retrying. Never edit event ordering or delete pending
records to make a dashboard appear green. Worker SIGTERM finishes its in-flight
event and stops before starting another; abrupt termination can replay an event,
which is why graph writes must stay idempotent.

## PostgreSQL backup and restore

```sh
python scripts/database_backup.py backup --output backups/catalog.dump
python scripts/database_backup.py restore --input backups/catalog.dump --database cinegraph_recovery
```

The tool creates a private PostgreSQL custom-format archive and SHA256 sidecar.
Restore verifies the digest, creates a **new** database, and refuses existing or
system/live target names. It never executes DROP DATABASE or pg_restore --clean.
For production Compose include global options before the subcommand:

```sh
python scripts/database_backup.py --compose-file compose.production.yaml --env-file .env.production backup --output backups/catalog.dump
```

A SHA256 sidecar detects accidental corruption, not a maliciously replaced backup
and checksum. Store backups encrypted, outside the host, with restricted access,
retention and immutable/versioned storage. A nightly backup command alone is not
a backup policy. Decide RPO/RTO and perform restore drills regularly.

After restoring, apply current SQL migrations to the recovery database and
validate row counts/accounts/outbox history. Point a recovery deployment at it
only after validation. The local verification restored a backup to a separate
database and checked 24 catalog rows.

## Graph recovery

The application graph is a projection of SQL. To rebuild, provision an empty
Neo4j database, pause projectors during configuration changes, point both worker
and API to it, then:

```sh
docker compose exec catalog python manage.py rebuild_graph
docker compose exec catalog python manage.py sync_graph
```

The command refuses a nonempty graph. It queues current SQL snapshots and retains
existing pending deletes/deadletters rather than silently forgetting them. Resolve
deadletters and check the operational status before routing traffic. Keep the old
graph available for rollback until the rebuild is verified.

## Retention

```sh
docker compose exec catalog python manage.py prune_records --processed-days 90 --event-days 365 --dry-run
# Review counts, then run the same command without --dry-run.
docker compose exec catalog python manage.py aggregate_analytics
docker compose exec catalog python manage.py clearsessions
```

Retention never removes pending/dead-lettered outbox entries. Choose retention
based on your audit/privacy requirements. Pruning interaction events changes the
source available for fresh analytics and subsequent daily aggregation.

## Upgrade and rollback

For the first upgrade from the original version, **stop legacy workers before
migration 0003**: the old global lock and new per-movie locks must not run together.
Web catalog edits can continue accumulating events. Run the initialization job,
then roll out the new workers and apps. Initialization applies migrations and
schema setup without waiting for the backlog to drain; a known deadletter cannot
block the entire release.

For subsequent releases use immutable images, backup before schema changes,
inspect migrations, and deploy through a staging environment first. Do not
blindly run reverse migrations when rolling back code; use expand/contract schema
changes and restore/redeploy if a migration is incompatible. Keep the prior image
digest and configuration alongside the release record.
