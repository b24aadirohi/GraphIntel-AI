# GraphIntel AI — AI and MCP configuration

## Local evidence mode

Leave `LLM_API_KEY` empty. The assistant retrieves movie descriptions and graph
attributes and returns source excerpts with identifiers. It explicitly reports
`mode: evidence`; this is retrieval, not generated natural-language reasoning.
The recommendation model uses TF-IDF similarity plus shared cast, directors and
genres. Candidate retrieval uses Neo4j full-text indexes and bounded relationship
expansion across the catalog. Model ranking uses a bounded candidate pool and
reuses cached TF-IDF matrices; this is not a large-scale quality benchmark.

## Hosted generation

Configure `.env`:

```dotenv
LLM_API_KEY=your-provider-key
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-or-deployment
LLM_AUTH_HEADER=Authorization
```

The adapter appends `/chat/completions` to the base URL. Alternatively provide a
complete chat-completions URL (including any required API-version query).
Provider credentials never enter browser responses or source control. Restart
API configuration with `docker compose up -d api` after editing `.env`.

For Azure's OpenAI-compatible endpoint, set the resource's base URL ending in
`/openai/v1`, the deployment name as `LLM_MODEL`, and `LLM_AUTH_HEADER=api-key`.
Use the endpoint/authentication that your deployed resource supports. This path
is based on the [Microsoft Foundry chat API reference](https://learn.microsoft.com/en-us/azure/foundry/openai/latest).
The project does not create a cloud account or deploy a model.

Catalog text and questions are passed as untrusted evidence under a separate
system instruction. Evidence has a character budget (`RAG_CONTEXT_CHARS`, default
6,000, clamped between 512 and 20,000). Answers missing citations or citing IDs
outside the retrieved evidence fail explicitly. Citation checking is not a
semantic fact-checker; generated output still requires evaluation.

Hosted generation is covered with a fake HTTP provider in tests. Calling a paid
provider requires your own key and is not part of automated local verification.

## MCP client

The server uses the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
1.x stdio transport, pinned below 2 for a stable API. It exposes:

- `search_movies(q, limit)`
- `get_movie(movie_id)`
- `recommend_movies(movie_id, limit)`

Check exact input schemas through the client's `tools/list` operation. The tools
are read-only and do not allow arbitrary Cypher or catalog mutations.

After starting and seeding the Compose stack, configure a local MCP client:

```json
{
  "mcpServers": {
    "cinegraph": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/cinegraph-ai",
        "--env-file", "/absolute/path/to/cinegraph-ai/.env",
        "cinegraph-mcp"
      ]
    }
  }
}
```

Replace both absolute paths; on Windows use JSON-escaped backslashes or forward
slashes. If the client cannot find `uv`, use its absolute executable path. The
MCP process connects to Neo4j on the host port configured in `.env`, not the
container-internal `neo4j` hostname. MCP calls do not create dashboard usage
events; those metrics describe FastAPI requests only.

Run the protocol test against the local databases with:

```sh
uv run --env-file .env --env-file .env.integration pytest tests/test_mcp.py -q
```
