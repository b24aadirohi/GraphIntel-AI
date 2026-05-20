import os
from contextlib import asynccontextmanager
from datetime import date

import django
from django.db import DatabaseError, close_old_connections, connection
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
from pydantic import BaseModel, Field, field_validator

from cinegraph.api.schemas import (
    Analytics,
    ChatResponse,
    GraphResponse,
    MoviePage,
    Recommendations,
    Stats,
)
from cinegraph.shared.graph import GraphRepository, Movie
from cinegraph.shared.observability import install_api_observability
from cinegraph.shared.rag import ProviderError, chat
from cinegraph.shared.rate_limit import RateLimitUnavailable
from cinegraph.shared.recommendations import recommend
from cinegraph.shared.security import check_security_readiness, close_api_security, install_api_security


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("question cannot be blank")
        return value.strip()


def create_app(repository=None):
    @asynccontextmanager
    async def lifespan(app):
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinegraph.catalog.settings")
        django.setup()
        app.state.repository = repository or GraphRepository()
        try:
            yield
        finally:
            close_api_security(app)
            if repository is None:
                app.state.repository.close()

    app = FastAPI(
        title="GraphIntel AI — Analytics & Conversational Intelligence API",
        description="Python APIs for Neo4j graph retrieval, explainable ML recommendations, "
        "digital analytics and source-grounded conversational RAG. Film data is the reference dataset.",
        lifespan=lifespan,
    )

    def record(kind):
        from cinegraph.catalog.analytics import record_event
        close_old_connections()
        try:
            record_event(kind)
        finally:
            close_old_connections()

    async def unavailable(request: Request, exc: Exception):
        return JSONResponse(status_code=503, content={"detail": "Database service unavailable"})

    for error in (Neo4jError, ServiceUnavailable, SessionExpired, DatabaseError, RateLimitUnavailable):
        app.add_exception_handler(error, unavailable)

    @app.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/live")
    def live():
        return {"status": "ok"}

    @app.get("/ready")
    @app.get("/health")
    def health(request: Request):
        check_security_readiness(request.app)
        request.app.state.repository.health()
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        finally:
            close_old_connections()
        return {"status": "ok", "graph": "ok", "catalog": "ok"}

    @app.get("/movies", response_model=MoviePage)
    def movies(request: Request, q: str = Query("", max_length=500),
               limit: int = Query(20, ge=1, le=100),
               cursor: str | None = Query(None, max_length=4096)):
        try:
            page = request.app.state.repository.search_page(q, limit, cursor)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        record("search")
        return page

    @app.get("/movies/{movie_id}", response_model=Movie)
    def movie(request: Request, movie_id: str):
        item = request.app.state.repository.get_movie(movie_id)
        if item is None:
            raise HTTPException(404, "Movie not found")
        return item

    @app.get("/recommendations/{movie_id}", response_model=Recommendations)
    def recommendations(request: Request, movie_id: str, limit: int = Query(5, ge=1, le=20)):
        try:
            items = recommend(request.app.state.repository, movie_id, limit)
        except LookupError as exc:
            raise HTTPException(404, "Movie not found") from exc
        record("recommendation")
        return {"items": items}

    @app.get("/graph", response_model=GraphResponse)
    def graph(request: Request, limit: int = Query(30, ge=1, le=100)):
        return request.app.state.repository.graph(limit)

    @app.get("/stats", response_model=Stats)
    def stats(request: Request):
        return request.app.state.repository.stats()

    @app.get("/operations")
    def operations():
        from cinegraph.catalog.projection import projection_status
        close_old_connections()
        try:
            return projection_status()
        finally:
            close_old_connections()

    @app.get("/analytics", response_model=Analytics)
    def analytics(start: date | None = None, end: date | None = None):
        from cinegraph.catalog.analytics import report
        if start and end and start > end:
            raise HTTPException(422, "start must be on or before end")
        close_old_connections()
        try:
            return report(start, end)
        finally:
            close_old_connections()

    @app.post("/chat", response_model=ChatResponse)
    def ask(request: Request, body: ChatRequest):
        result = chat(request.app.state.repository, body.question)
        record("chat")
        return result

    install_api_security(app)
    install_api_observability(app)
    return app


app = create_app()
