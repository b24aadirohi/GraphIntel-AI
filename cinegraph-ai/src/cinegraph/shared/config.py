"""Environment-only configuration, loaded at service startup."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_auth_header: str
    context_chars: int

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("NEO4J_URI", "bolt://localhost:7688"),
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "cinegraph-local-password"),
            os.getenv("NEO4J_DATABASE", "neo4j"),
            os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            os.getenv("LLM_API_KEY", ""),
            os.getenv("LLM_MODEL", ""),
            os.getenv("LLM_AUTH_HEADER", "Authorization"),
            max(512, min(int(os.getenv("RAG_CONTEXT_CHARS", "6000")), 20000)),
        )
