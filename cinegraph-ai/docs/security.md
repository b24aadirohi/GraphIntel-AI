# GraphIntel AI — Security model

## Authentication and authorization

Flask accepts existing Django accounts. Credentials are checked through Django's
password hasher. The browser receives an opaque database-session identifier,
not the API service key. Session rotation on login prevents session fixation;
logout deletes the server-side session. Sessions expire after eight hours and
are rejected after password change, deactivation or explicit session revocation.
CSRF tokens protect login, logout and browser POST requests. Production cookies
are Secure, HttpOnly and SameSite=Lax. Staff accounts alone can access usage
analytics; Django model permissions govern catalog administration.

FastAPI is private to the portal and operational clients. It accepts the
`CINEGRAPH_API_KEY` bearer credential using constant-time comparison. This is a
service credential, not a per-user API token system. Do not distribute it to end
users; use a gateway/identity provider with scoped credentials if external API
consumers are required. MCP is a local stdio process whose client already has
local database credentials; it is not exposed as an anonymous network service.

## Production checks

`CINEGRAPH_ENV=production` requires authentication, strong distinct
API/session/database credentials, PostgreSQL, authenticated Redis and valid HTTPS
origins. Unknown environments and invalid boolean flags are errors. Production
rejects debug flags. `scripts/configure.py --production --domain ...` generates
private random configuration and refuses to overwrite existing credentials.
Keep that file out of source control; use your deployment secret store for a
managed environment. Database connections in the single-host Compose network are
private; use TLS-enabled managed-database URLs on untrusted networks.

## Proxy trust

`DJANGO_TRUST_PROXY=true` trusts the configured ingress's original-protocol and
client-IP headers. It is safe only when application ports are inaccessible to
untrusted clients. The supplied Caddy gateway overwrites `X-Forwarded-For` with
its actual connecting client and sets the forwarded protocol. Configure an
upstream load balancer/CDN's trusted proxy addresses deliberately; do not accept
arbitrary forwarded headers from the Internet. Kubernetes policies restrict web
ingress to the ingress-controller namespace; adapt that namespace to your cluster.

Without the explicit trust flag, forwarded client-IP headers are ignored.
Login throttles use both account and client-IP counters so one account's attacks
do not consume every user's allowance through a shared gateway.

## Limits and failure behavior

Redis uses an atomic Lua counter and expiry, shared across processes. Default
API quota is 240 requests/minute (`API_RATE_LIMIT`), chat quota 20/minute
(`CHAT_RATE_LIMIT`), and login quotas 30/client and 10/account per 15 minutes.
API/chat quotas are aggregate service protection, not per-user usage billing.
Redis failure denies protected requests with 503; quota exhaustion returns 429
and Retry-After. Requests have bounded bodies and read deadlines. Connection,
graph query, browser proxy and hosted-provider timeouts are bounded.

SQL and Cypher use parameters. Full-text input is tokenized as literal terms;
model-produced queries never execute. HTML uses escaped templates/textContent.
Provider evidence and response sizes are bounded, and citation IDs must belong
to retrieved sources. These measures do not prove model factual accuracy or
eliminate every prompt-injection possibility; evaluate your chosen model and data.

## Logs and secrets

Application request logs include a bounded request ID, route template, method,
status and duration. They omit raw queries, payloads and authorization headers.
Outbox errors persist allowlisted codes/messages rather than exception strings.
Prometheus labels use route templates to avoid unbounded cardinality.

Rotate the API key and restart API/dashboard together; existing in-flight calls
may briefly receive 401. Rotating the Django secret invalidates browser sessions.
Rotate database credentials through the database provider before changing app
configuration; simply changing a Compose environment variable does not rotate
an existing persisted database. Backups contain credential hashes and personal
account data and must be encrypted/access-controlled by your storage system.

This implementation does not add enterprise SSO/MFA, per-tenant isolation or
external API client provisioning. Those need explicit identity and tenancy
requirements before public multi-tenant operation.
