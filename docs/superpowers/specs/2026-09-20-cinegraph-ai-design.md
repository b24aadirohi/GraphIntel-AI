# CineGraph AI — proposed project design

## Objective

Create a runnable Python portfolio project demonstrating Flask, FastAPI, Django,
Neo4j, analytics, machine learning, graph-grounded conversational AI, MCP, and
delivery automation through one coherent movie discovery application.

Create the application in `cinegraph-ai/` within this workspace. Existing movie
examples remain available. Python is the primary language; the role asks for one
or multiple languages, so C++ and Scala are not necessary for this project.

## Approaches considered

1. **Recommended: three focused services with shared domain code.** Django owns
   catalog administration, Flask serves the analytics dashboard, and FastAPI
   owns search and AI endpoints. This demonstrates all three frameworks with
   clear responsibilities, at the cost of running several processes.
2. **Three equivalent implementations of the same API.** Easier framework
   comparison, but duplicates business logic and provides a weaker end-to-end
   project story.
3. **Cloud-first data platform.** Adds managed ingestion, Spark, and model
   hosting immediately, but introduces account, cost, and infrastructure
   dependencies before the core application works.

## Architecture

| Component | Responsibility |
| --- | --- |
| Django | Authenticated staff administration of movies, people, genres, and ingestion jobs; SQL-backed audit records |
| PostgreSQL | Authoritative catalog, Django users, ingestion status, analytics events, and reporting tables |
| Neo4j | Searchable projection of movies, people, genres, and their relationships |
| FastAPI | Validated search, graph traversal, recommendations, and conversational RAG endpoints |
| Flask | Dashboard with charts, graph exploration, chat UI, and CSV exports |
| Shared Python package | Configuration, parameterized graph queries, ingestion, retrieval, recommendation scoring, and provider adapters |
| MCP server | Read-only movie search, movie detail, and recommendation tools using the shared services |

Django publishes catalog changes through a SQL outbox. A worker retries
idempotent Neo4j upserts and records synchronization status. SQL is the source
of truth; the graph can be rebuilt from it. Failed graph writes remain visible
and retryable instead of silently losing changes. Flask obtains application
data from FastAPI over HTTP. Django, FastAPI, and Flask each have a separate
entry point and container.

## User workflows

1. Start the stack and import a bundled, deterministic sample catalog.
2. Search movies, inspect cast and genre relationships, and explore graph data.
3. Request recommendations with an explanation of shared genres or people and
   a content-similarity score.
4. Ask a movie question and see a response with retrieved movie identifiers and
   source snippets.
5. Review catalog statistics and search/recommendation activity in the dashboard.
6. Export reporting data as CSV for Excel, Power BI, or Tableau.
7. Log into Django admin, edit a movie, and observe its graph synchronization status.
8. Connect an MCP client and invoke the same read-only discovery tools.

## Data and analytics

Graph nodes are Movie, Person, and Genre. Relationships are ACTED_IN,
DIRECTED, and IN_GENRE. Stable application identifiers and uniqueness
constraints support repeatable ingestion.

PostgreSQL stores catalog records and timestamped interaction events. An
idempotent aggregation command populates daily reporting tables for searches,
recommendation requests, and chat requests. Dashboard charts distinguish
catalog statistics from observed usage; the UI identifies bundled sample data.

The first recommendation model combines TF-IDF cosine similarity over movie
descriptions with graph overlap. Include a small held-out relevance fixture and
an evaluation command. This is classical machine learning; it must not be
described as deep learning or proof of large-scale processing.

## RAG and context engineering

Retrieve relevant descriptions, expand a bounded set of cast and genre
relationships, and assemble context within a configured size limit. Treat movie
text as untrusted data, keep it separate from system instructions, and require
answers to cite retrieved source identifiers. Never execute model-generated
Cypher or SQL.

Provide a local evidence-only mode that renders retrieved facts without an LLM
and clearly labels the response. Add a configurable hosted LLM adapter with
timeouts and explicit provider errors. A missing API key selects evidence-only
mode; a failed configured provider returns a clear error, not a fabricated
successful generation. Tests use a fake provider and do not incur API charges.

Evaluate retrieval against known relevant movies, citation validity, empty
retrieval behavior, context limits, and malicious instructions in catalog text.
Do not claim that citation validation alone proves factual accuracy.

## MCP

Expose `search_movies`, `get_movie`, and `recommend_movies` through the official
Python MCP SDK with a local stdio transport. Tools have validated inputs,
bounded result sizes, and no arbitrary database execution or write capability.
Include a client configuration example and a protocol-level smoke test.

## Local operation and deployment

Docker Compose starts PostgreSQL, Neo4j, the three web services, and the catalog
worker. Include schema migrations, a repeatable seed command, health checks,
an environment example, and instructions for Windows PowerShell and Linux/macOS
shells. Credentials are supplied through environment configuration.

Include Kubernetes manifests for application services and document external
database connection settings and secret provisioning. A cloud deployment guide
describes an Azure path and the configuration required for hosted generation.
Provisioning paid infrastructure and claiming cloud deployment are outside the
initial acceptance criteria.

GitHub Actions runs linting, unit tests, database-backed integration tests, and
container builds. It must not publish images or deploy infrastructure without
explicit deployment configuration.

## Error handling and access

Django administration requires staff authentication. Use validated and bounded
API inputs, parameterized queries, request timeouts, escaped user-facing text,
and service configuration through environment variables. Database unavailability
produces a service-unavailable response. Empty search results are successful
empty responses. Public discovery endpoints are read-only; ingestion and catalog
writes are not exposed anonymously. Local launch defaults bind exposed services
to loopback. Document additional authentication and rate limiting required before
public deployment.

## Project structure

```text
cinegraph-ai/
  pyproject.toml
  README.md
  .env.example
  compose.yaml
  Dockerfile
  src/cinegraph/
    shared/
    catalog/
    api/
    dashboard/
    mcp_server/
  data/
  tests/
  deploy/kubernetes/
  docs/
```

The repository-level GitHub workflow targets the new project explicitly.

## Acceptance criteria

- One documented Compose workflow launches all three frameworks and both databases.
- Seed data can be imported twice without creating duplicates.
- Django catalog edits appear in Neo4j through retryable synchronization.
- Search, graph exploration, recommendations, and dashboard charts use real data.
- The assistant returns sourced evidence locally and supports configured generation.
- CSV exports contain the same filtered reporting data shown in the dashboard.
- An MCP client can discover and invoke the three documented tools.
- Tests exercise graph queries against Neo4j, SQL migrations and synchronization,
  service endpoints, retrieval/citation behavior, and MCP tool invocation.
- Documentation includes architecture, operating commands, test results, and an
  honest requirement-to-feature matrix.

## Job requirement mapping and boundaries

| Requirement | Project evidence |
| --- | --- |
| Python; Windows/Linux | Python services and cross-platform launch documentation |
| Django, Flask, analytics | Admin, dashboard, charts, and export workflows |
| SQL/NoSQL; data warehousing | PostgreSQL records/reporting tables and Neo4j projection |
| Machine learning | Evaluated content and graph recommendation model |
| NLP, RAG, context engineering, GenAI | Retrieval, bounded context, provider adapter, citations, and evaluation |
| Graph databases | Neo4j schema, traversal, synchronization, and integration tests |
| MCP | Working discovery tools and client example |
| Docker/Kubernetes | Compose stack, images, and deployment manifests |
| GitHub and CI/CD | Automated checks and image builds; deployment documented separately |
| Cloud/Azure | Configuration and deployment guide; hosted execution requires credentials |
| Power BI/Tableau/Office | Compatible CSV exports; no claim of authored native dashboards |

Spark/Databricks pipelines, TensorFlow/Keras/CUDA training, OpenCV, and
TensorFlow.js are optional follow-on work, not initial implemented capabilities.
They need a justified workload rather than unused dependencies. This project
provides demonstrable project experience, not a claim of one year of employment.

## Review state

Approved by the user on 2026-09-20 with instructions to proceed without further
questions. Implemented in cinegraph-ai; actual verification is recorded in
cinegraph-ai/docs/verification.md. Library versions are locked in uv.lock.
