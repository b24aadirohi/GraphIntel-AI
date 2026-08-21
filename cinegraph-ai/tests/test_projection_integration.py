"""Real SQL outbox-to-Neo4j roundtrip, isolated to a unique synthetic movie."""

import os
from uuid import uuid4

import pytest

from cinegraph.catalog.models import Movie, OutboxEvent
from cinegraph.catalog.projection import sync_pending
from cinegraph.shared.graph import GraphRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        os.getenv("CINEGRAPH_INTEGRATION") != "1", reason="Requires live PostgreSQL and Neo4j"
    ),
]


def test_sql_outbox_projects_create_edit_and_delete():
    repository = GraphRepository()
    movie_id = f"projection-test-{uuid4().hex}"
    try:
        repository.ensure_schema()
        movie = Movie.objects.create(
            id=movie_id,
            title="Projection integration original",
            released=2025,
            summary="A cartographer discovers a lost trail.",
            genres=["Adventure"],
            cast=["Projection Test Actor"],
            directors=["Projection Test Director"],
        )
        assert sync_pending(repository) == 1
        result = repository.get_movie(movie_id)
        assert result["title"] == movie.title
        assert result["cast"] == movie.cast
        movie.title = "Projection integration edited"
        movie.genres = ["Mystery"]
        movie.cast = ["Projection Test Replacement"]
        movie.save()
        assert sync_pending(repository) == 1
        result = repository.get_movie(movie_id)
        assert result["title"] == movie.title
        assert result["genres"] == ["Mystery"]
        assert result["cast"] == ["Projection Test Replacement"]
        movie.delete()
        assert sync_pending(repository) == 1
        assert repository.get_movie(movie_id) is None
        assert not OutboxEvent.objects.filter(movie_id=movie_id, processed_at__isnull=True).exists()
    finally:
        Movie.objects.filter(pk=movie_id).delete()
        repository.delete_movie(movie_id)
        repository.close()
