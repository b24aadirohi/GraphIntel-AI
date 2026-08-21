from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import Client

from cinegraph.catalog.models import Movie, OutboxEvent
from cinegraph.catalog.projection import sync_pending

pytestmark = pytest.mark.django_db


@pytest.fixture
def movie():
    return Movie.objects.create(
        id="test-movie",
        title="Test Film",
        released=2020,
        summary="A pilot discovers a forgotten island.",
        genres=["Adventure"],
        cast=["Actor One"],
        directors=["Director One"],
    )


def test_seed_idempotent():
    call_command("seed")
    count = Movie.objects.count()
    assert count >= 20
    pending = OutboxEvent.objects.count()
    call_command("seed")
    assert Movie.objects.count() == count
    assert OutboxEvent.objects.count() == pending
    call_command("seed", requeue=True)
    assert OutboxEvent.objects.count() == pending + count


def test_outbox_rolls_back_with_catalog():
    with pytest.raises(RuntimeError), transaction.atomic():
        Movie.objects.create(id="rolled-back", title="Lost", released=2020, summary="Never committed")
        raise RuntimeError("rollback")
    assert not Movie.objects.exists()
    assert not OutboxEvent.objects.exists()


def test_ordered_update_and_delete_projection(movie):
    repository = Mock()
    movie.title = "Updated Film"
    movie.genres = ["Mystery"]
    movie.save()
    Movie.objects.filter(pk=movie.pk).delete()
    assert sync_pending(repository) == 3
    assert repository.upsert_movie.call_args_list[0].args[0]["title"] == "Test Film"
    assert repository.upsert_movie.call_args_list[1].args[0]["title"] == "Updated Film"
    assert repository.upsert_movie.call_args_list[1].args[0]["genres"] == ["Mystery"]
    repository.delete_movie.assert_called_once_with("test-movie")
    assert sync_pending(repository) == 0


def test_projection_retries_without_reordering(movie):
    repository = Mock()
    movie.title = "Later state"
    movie.save()
    repository.upsert_movie.side_effect = RuntimeError("Neo4j offline")
    assert sync_pending(repository) == 0
    first, second = list(OutboxEvent.objects.all())
    assert first.attempts == 1
    assert first.processed_at is None
    assert first.error_code == "projection_failed"
    assert "Neo4j offline" not in first.last_error
    assert second.attempts == 0
    repository.upsert_movie.side_effect = None
    from django.utils import timezone

    OutboxEvent.objects.filter(pk=first.pk).update(next_attempt_at=timezone.now())
    assert sync_pending(repository) == 2
    first.refresh_from_db()
    assert first.attempts == 2
    assert first.last_error == ""
    assert first.processed_at is not None
    assert repository.upsert_movie.call_args.args[0]["title"] == "Later state"


def test_partial_save_outbox_matches_sql(movie):
    movie.title = "Unsaved title"
    movie.summary = "A revised summary"
    movie.save(update_fields=["summary"])
    latest = OutboxEvent.objects.latest("id")
    assert latest.payload["title"] == "Test Film"
    assert latest.payload["summary"] == "A revised summary"


def test_admin_requires_staff_and_permissions(movie):
    client = Client()
    assert client.get("/admin/catalog/movie/").status_code == 302
    user = get_user_model().objects.create_user(username="reader", password="example-password")
    client.force_login(user)
    assert client.get("/admin/catalog/movie/").status_code == 302
    user.is_staff = True
    user.save()
    assert client.get("/admin/catalog/movie/").status_code == 403
    user.is_superuser = True
    user.save()
    assert client.get("/admin/catalog/movie/").status_code == 200


def test_health_checks_database():
    response = Client().get("/health/")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


@pytest.mark.parametrize("value", [{"bad": "value"}, [None], [""], [123]])
def test_movie_rejects_invalid_lists(value):
    with pytest.raises(ValidationError):
        Movie.objects.create(id="bad", title="Bad", released=2020, summary="Invalid", genres=value)


def test_delete_and_outbox_rollback_together(movie):
    initial_events = OutboxEvent.objects.count()
    with pytest.raises(RuntimeError), transaction.atomic():
        Movie.objects.filter(pk=movie.pk).delete()
        raise RuntimeError("rollback")
    assert Movie.objects.filter(pk=movie.pk).exists()
    assert OutboxEvent.objects.count() == initial_events


@pytest.mark.django_db(transaction=True)
def test_sync_command_drains_batches_and_closes(movie, monkeypatch):
    from cinegraph.catalog.management.commands import sync_graph

    movie.title = "Second version"
    movie.save()
    repository = Mock()
    monkeypatch.setattr(sync_graph, "GraphRepository", lambda: repository)
    call_command("sync_graph", batch_size=1)
    assert repository.upsert_movie.call_count == 2
    assert not OutboxEvent.objects.filter(processed_at__isnull=True).exists()
    repository.close.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_sync_command_failure_preserves_retry_and_closes(movie, monkeypatch):
    from django.core.management.base import CommandError

    from cinegraph.catalog.management.commands import sync_graph

    repository = Mock()
    repository.upsert_movie.side_effect = RuntimeError("offline")
    monkeypatch.setattr(sync_graph, "GraphRepository", lambda: repository)
    with pytest.raises(CommandError, match="backlog remains"):
        call_command("sync_graph")
    assert OutboxEvent.objects.filter(processed_at__isnull=True, attempts=1).count() == 1
    repository.close.assert_called_once()


def test_seed_preserves_edits_unless_reset_requested():
    call_command("seed")
    movie = Movie.objects.get(pk="movie-001")
    original_title = movie.title
    movie.title = "An administrator's corrected title"
    movie.summary = "An administrator's corrected summary"
    movie.save()
    pending = OutboxEvent.objects.count()
    call_command("seed")
    movie.refresh_from_db()
    assert movie.title == "An administrator's corrected title"
    assert movie.summary == "An administrator's corrected summary"
    assert OutboxEvent.objects.count() == pending
    call_command("seed", reset_existing=True)
    movie.refresh_from_db()
    assert movie.title == original_title
    assert OutboxEvent.objects.count() == pending + 1


def test_requeue_projects_current_catalog_including_custom_movies(movie):
    call_command("seed")
    sample = Movie.objects.get(pk="movie-001")
    sample.title = "Updated sample title"
    sample.save()
    previous = OutboxEvent.objects.latest("id").id
    call_command("seed", requeue=True)
    queued = list(OutboxEvent.objects.filter(id__gt=previous))
    assert len(queued) == Movie.objects.count()
    by_movie = {event.movie_id: event.payload for event in queued}
    assert by_movie[movie.pk] == movie.as_dict()
    assert by_movie[sample.pk] == sample.as_dict()


@pytest.mark.parametrize("movie_id", [".", "..", "a/b", "a b", "é", "a\n", "x" * 129])
def test_catalog_rejects_ids_that_cannot_be_routed(movie_id):
    with pytest.raises(ValidationError):
        Movie.objects.create(id=movie_id, title="Invalid identifier", released=2020, summary="Summary")
    assert not OutboxEvent.objects.exists()


@pytest.mark.parametrize("movie_id", ["custom.film", "ABC_123-test", "x" * 128])
def test_catalog_accepts_canonical_identifiers(movie_id):
    movie = Movie.objects.create(id=movie_id, title="Valid identifier", released=2020, summary="Summary")
    assert OutboxEvent.objects.get().movie_id == movie.pk
