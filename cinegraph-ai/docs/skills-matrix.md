# GraphIntel AI — role capability and evidence matrix

GraphIntel AI demonstrates equivalent project experience through runnable code,
operational tooling and verification evidence. The film catalog is a reference
dataset for data engineering, analytics and conversational AI workflows.

| Requested capability | Repository evidence | Implementation scope |
| --- | --- | --- |
| Windows and/or Linux operating systems and applications | PowerShell/POSIX startup instructions, environment configuration, service health, logs and container operations | Cross-platform instructions; Linux CI configured; local verification on macOS/Docker |
| Python, C++ or Scala | Python services, ingestion/projection, analytics, ML and MCP tooling | Python implemented; no C++ or Scala components |
| Django, Flask and FastAPI | Django catalog/admin, Flask exploration and reporting UI, typed FastAPI endpoints | All three implemented |
| Advanced analytics and visualization | Interactive relationship graph, filtered activity charts, daily aggregates and CSV exports | Implemented; no claim of large-scale statistical analytics |
| Microsoft Office, Power BI and Tableau | CSV export suitable for Excel, Power BI and Tableau import | Interoperable export; native workbooks and live BI connectors not included |
| SQL/NoSQL and data management | PostgreSQL source of truth, Neo4j graph storage, transactional outbox and idempotent projection | Implemented and integration-tested |
| Digital analytics and warehousing | Timestamped interaction events, daily metrics and reporting APIs | Small analytical reporting model; no enterprise warehouse or lakehouse |
| Machine learning and NLP | TF-IDF features, graph recommendation signals, retrieval and held-out evaluation | Classical ML implemented; benchmark is small and synthetic |
| Prompt/context engineering, LLMs and GenAI | Explicit generation instructions, bounded evidence, hosted provider adapter and source validation | Implemented; hosted generation requires credentials; no paid provider call verified |
| NLP, RAG and conversational GenAI applications | Indexed retrieval, ranked context, sourced chat and evidence inspection | Local evidence mode works; generated mode uses configured provider |
| Azure AI Foundry | Compatible endpoint/auth configuration is documented in the AI guide | No Foundry SDK integration, workspace deployment or live verification |
| Databricks and Spark | Potential batch ingestion/analytics extension | Not implemented; present dataset does not demonstrate big-data scale |
| TensorFlow, Keras and CUDA | Potential neural embedding comparison against the existing ML baseline | Not implemented; no trained neural model or GPU benchmark |
| OpenCV and TensorFlow.js | Potential image-similarity/browser inference extension using licensed media | Not implemented |
| Azure, AWS and GCP | Azure Kubernetes deployment guide and portable container configuration | Azure path documented; no cloud resources provisioned; AWS/GCP integrations not implemented |
| Neo4j and Azure Cosmos DB graph databases | Neo4j schema, indexes, constraints, traversal and integration tests | Neo4j implemented; Cosmos DB would require another storage adapter |
| Docker and Kubernetes | Hardened image, Compose, deployment/probe/scaling/network-policy manifests | Docker verified locally; Kubernetes rollout not executed |
| Model Context Protocol (MCP) | Official SDK stdio server, discovery tools and real protocol subprocess tests | Implemented and tested |
| GitHub and CI/CD | Lint, database tests, audit, image scan, SBOM and gated image publication workflow | Configuration validated locally; no remote release executed |
| One year of experience or equivalent project experience | End-to-end project, design decisions, recovery checks and runnable demonstration | Project evidence; no employment-duration claim |

## Demonstration sequence

1. Open the analytics/exploration portal and explain the three Python frameworks.
2. Edit a catalog record in Django; trace SQL change delivery into the Neo4j graph.
3. Demonstrate indexed search, relationship-based recommendations and their scores.
4. Ask a dataset question; inspect retrieved sources and distinguish evidence
   excerpts from optional model-generated responses.
5. Show event reporting and CSV export, then invoke an MCP discovery tool.
6. Explain retry recovery, access controls, monitoring and the CI release gate.

See [project descriptions](project-profile.md), [verification](verification.md),
[AI/MCP configuration](ai-and-mcp.md) and [deployment](deployment.md).
