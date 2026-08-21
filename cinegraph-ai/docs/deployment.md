# GraphIntel AI — Production deployment

## Single-host deployment

A domain, DNS access, Docker host, storage/backup policy and secret handling are
required. Generate a separate deployment configuration; never reuse local demo
passwords:

```sh
python scripts/configure.py --production --domain films.your-domain.com
docker build -t cinegraph-ai:local .
# For a release, set CINEGRAPH_IMAGE in .env.production to your immutable registry digest.
docker compose --env-file .env.production -f compose.production.yaml up -d
docker compose --env-file .env.production -f compose.production.yaml exec catalog python manage.py createsuperuser
```

Create DNS records for the supplied domain and `admin.` subdomain pointing at the
host. The Caddy gateway obtains TLS certificates and redirects HTTP to HTTPS.
Only the gateway publishes ports 80/443; API, PostgreSQL, Neo4j and Redis remain
private. App containers run as nonroot with a read-only filesystem, temporary
writable `/tmp`, dropped capabilities, no privilege escalation, resource limits
and log rotation. Redis is authenticated and uses persistent counters; an outage
fails protected requests closed.

Public TLS issuance was not performed in local verification. Caddy configuration
was validated, and app/database services ran under production configuration in
an isolated local stack. Public DNS, certificate issuance, backups, ingress
rules and host maintenance must be accepted in your environment.

Production bootstrap applies migrations and graph schema only. It neither seeds
fictional data nor waits for the outbox to drain. Import your catalog through
supported model/admin operations and let workers project it. Before the initial
upgrade from v0.1, follow the legacy-worker shutdown step in
[operations](operations.md).

The sample Compose deployment is single-host and uses local database volumes;
it is not a highly available database system. Use managed PostgreSQL/Redis and a
supported Neo4j deployment for database HA, backups and recovery objectives.
Configure TLS database URLs when traffic crosses an untrusted network.

## Kubernetes

The manifests provide two application replicas, rolling updates, probes,
resource requests/limits, disruption budgets, API CPU autoscaling, spread
preferences, restricted pod security, no service-account token mounting, and
network policies. External PostgreSQL, Neo4j and Redis are required.

1. Replace image references in `services.yaml` and `init-job.yaml` with the same
   immutable image digest compatible with the cluster architecture. Update ConfigMap origins/hosts from
   the example domain. Use your ingress controller to terminate TLS and route
   the dashboard and admin hostnames to their respective ClusterIP services.
2. Update network-policy ingress-controller namespace and egress destinations to
   match your actual cluster/database networks. The supplied policy permits DNS,
   HTTPS providers and database ports; tighten destination ranges before release.
3. Create the namespace and secret using values appropriate for external services:

```sh
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl -n cinegraph create secret generic cinegraph-secrets --from-env-file=.env.kubernetes
kubectl apply -f deploy/kubernetes/config.yaml
kubectl apply -f deploy/kubernetes/init-job.yaml
kubectl -n cinegraph wait --for=condition=complete job/cinegraph-init --timeout=300s
kubectl apply -f deploy/kubernetes/services.yaml
kubectl apply -f deploy/kubernetes/network-policy.yaml
kubectl apply -f deploy/kubernetes/availability.yaml
kubectl -n cinegraph rollout status deployment/api
```

The private secret file supplies `DATABASE_URL`, `NEO4J_URI`, `NEO4J_PASSWORD`,
`REDIS_URL`, `CINEGRAPH_API_KEY`, `DJANGO_SECRET_KEY`, and optional LLM credentials.
It must use production-grade generated credentials. Kubernetes API readiness
alone is not deployment acceptance: verify login, secure cookies, CSRF, catalog
projection, metrics, provider budget limits and restore procedures through your
actual ingress. CPU HPA requires metrics-server. Enforcing NetworkPolicy requires
a compatible CNI.

On subsequent releases create a uniquely named migration Job and wait for it
before updating app Deployments. Preserve the old image reference for rollback.
No actual cluster rollout was performed in this workspace.

## CI and image release

`cinegraph-ai.yml` runs lint, migration checks, real PostgreSQL/Neo4j/Redis tests,
Python vulnerability audit, evaluation, container build, Trivy HIGH/CRITICAL scan
and a CycloneDX SBOM artifact. Actions are pinned to commit IDs.

`cinegraph-release.yml` is manually triggered and reruns the verification workflow
before building a Linux AMD64 image tagged with the Git commit. The release job
loads that image locally, checks runtime libraries, scans HIGH/CRITICAL findings,
and uploads its CycloneDX SBOM. Only then does it push the identical image to
GHCR without rebuilding and record its registry digest. No provenance attestation
is claimed; other architectures require their own release validation. Configure
the `production-image` GitHub environment's approval and branch policies before
using it. Adding an environment name in YAML alone does not configure reviewers.
The workflow publishes an image; it does not automatically change a live cluster.
No workflow was triggered or image pushed during this local work.

## Azure path

Use AKS with ACR or GHCR, managed PostgreSQL/Redis and a reachable Neo4j service.
Configure registry pull permissions and follow the same migration/deployment
sequence. Microsoft documents the [AKS registry setup](https://learn.microsoft.com/en-us/azure/aks/tutorial-kubernetes-prepare-acr).
Use the model endpoint/auth settings in [AI configuration](ai-and-mcp.md) for
Azure-hosted generation. Cloud provisioning and paid provider calls are outside
local verification.

Django production settings follow its [deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
HSTS is enabled, but browser preload is deliberately not enabled/submitted:
preload is a domain-owner commitment, not an application default.
