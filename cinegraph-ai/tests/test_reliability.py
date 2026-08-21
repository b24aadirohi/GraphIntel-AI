from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from cinegraph.catalog.models import Movie, OutboxEvent
from cinegraph.catalog.projection import projection_status, sync_pending

pytestmark = pytest.mark.django_db


def create_movie(identifier):
    return Movie.objects.create(id=identifier, title=identifier, released=2020, summary="Original summary")


def test_failure_does_not_stall_other_movie_and_is_sanitized():
    first = create_movie("failed")
    first.title = "Newer state"
    first.save()
    create_movie("healthy")
    repository = Mock()

    def write(payload):
        if payload["id"] == "failed":
            raise RuntimeError("password=secret-canary")

    repository.upsert_movie.side_effect = write
    assert sync_pending(repository) == 1
    events = list(OutboxEvent.objects.filter(movie_id="failed"))
    assert events[0].attempts == 1
    assert events[0].next_attempt_at > timezone.now()
    assert events[0].error_code == "projection_failed"
    assert "secret-canary" not in events[0].last_error
    assert events[1].attempts == 0
    assert sync_pending(repository) == 0


def test_deadletter_blocks_same_movie_until_explicit_retry():
    movie = create_movie("retry")
    movie.title = "Latest"
    movie.save()
    repository = Mock()
    repository.upsert_movie.side_effect = RuntimeError("failed")
    first, later = OutboxEvent.objects.filter(movie_id=movie.pk)
    for _ in range(5):
        OutboxEvent.objects.filter(pk=first.pk).update(next_attempt_at=timezone.now())
        assert sync_pending(repository) == 0
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.dead_lettered_at is not None
    assert first.attempts == 5
    assert later.attempts == 0
    assert projection_status()["deadletters"] == 1
    call_command("retry_outbox", id=first.pk)
    first.refresh_from_db()
    assert first.dead_lettered_at is None
    assert first.attempts == 0
    repository.upsert_movie.side_effect = None
    assert sync_pending(repository) == 2
    assert repository.upsert_movie.call_args.args[0]["title"] == "Latest"


def test_retention_never_deletes_pending_or_deadletters():
    create_movie("pending")
    create_movie("dead")
    create_movie("done")
    past = timezone.now() - timedelta(days=100)
    OutboxEvent.objects.all().update(created_at=past)
    OutboxEvent.objects.filter(movie_id="dead").update(dead_lettered_at=past)
    OutboxEvent.objects.filter(movie_id="done").update(processed_at=past)
    call_command("prune_records", processed_days=30, event_days=90)
    assert set(OutboxEvent.objects.values_list("movie_id", flat=True)) == {"pending", "dead"}


def test_heartbeat_health_and_status():
    from cinegraph.catalog.projection import heartbeat

    with pytest.raises(CommandError):
        call_command("worker_health", worker_name="test-worker")
    heartbeat("test-worker")
    call_command("worker_health", worker_name="test-worker")
    assert projection_status()["last_heartbeat"] is not None


def test_rebuild_queues_current_custom_movies_without_erasing_pending(monkeypatch):
    from cinegraph.catalog.management.commands import rebuild_graph

    movie = create_movie("custom-film")
    movie.title = "Current edited title"
    movie.save()
    repository = Mock()
    repository.stats.return_value = {"movies": 0}
    monkeypatch.setattr(rebuild_graph, "GraphRepository", lambda: repository)
    call_command("rebuild_graph")
    assert OutboxEvent.objects.filter(movie_id=movie.pk).count() == 3
    assert OutboxEvent.objects.latest("id").payload["title"] == "Current edited title"
    repository.stats.return_value = {"movies": 1}
    with pytest.raises(CommandError, match="empty"):
        call_command("rebuild_graph")


def test_live_does_not_touch_database_and_ready_checks_migrations(monkeypatch):
    from django.test import Client

    from cinegraph.catalog import urls

    executor = Mock()
    executor.migration_plan.return_value = [object()]
    monkeypatch.setattr(urls, "MigrationExecutor", lambda _: executor)
    assert Client().get("/live/").status_code == 200
    assert Client().get("/ready/").status_code == 503
    executor.migration_plan.return_value = []
    assert Client().get("/health/").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_worker_sigterm_stops_between_events_and_marks_heartbeat(monkeypatch):
    import signal

    from cinegraph.catalog.management.commands import sync_graph
    from cinegraph.catalog.models import WorkerHeartbeat

    create_movie("shutdown-a")
    create_movie("shutdown-b")
    repository = Mock()
    repository.upsert_movie.side_effect = lambda payload: signal.raise_signal(signal.SIGTERM)
    monkeypatch.setattr(sync_graph, "GraphRepository", lambda: repository)
    old_handler = signal.getsignal(signal.SIGTERM)
    call_command("sync_graph", watch=True, worker_name="shutdown-test")
    repository.close.assert_called_once()
    assert repository.upsert_movie.call_count == 1
    assert OutboxEvent.objects.filter(processed_at__isnull=True).count() == 1
    assert WorkerHeartbeat.objects.get(pk="shutdown-test").status == "stopped"
    assert signal.getsignal(signal.SIGTERM) == old_handler


def test_retry_movie_command_keeps_original_event_identity():
    movie = create_movie("recover-movie")
    first = OutboxEvent.objects.get(movie_id=movie.pk)
    OutboxEvent.objects.filter(pk=first.pk).update(dead_lettered_at=timezone.now(), attempts=5)
    call_command("retry_outbox", movie_id=movie.pk)
    first.refresh_from_db()
    assert first.dead_lettered_at is None
    assert first.attempts == 0
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_workers_skip_busy_movie_without_reordering():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL")
    movie = create_movie("a-busy")
    movie.title = "Later state"
    movie.save()
    create_movie("z-independent")
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def write(payload):
        if payload["id"] == "a-busy" and payload["title"] == "a-busy":
            entered.set()
            assert release.wait(10), "Timed out waiting for second worker"
        calls.append((payload["id"], payload["title"]))

    repository = Mock()
    repository.upsert_movie.side_effect = write

    def run_worker(limit):
        close_old_connections()
        try:
            return sync_pending(repository, limit=limit)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        busy = pool.submit(run_worker, 1)
        try:
            assert entered.wait(5)
            independent = pool.submit(run_worker, 10)
            assert independent.result(timeout=5) == 1
            assert calls == [("z-independent", "z-independent")]
            assert OutboxEvent.objects.filter(movie_id="a-busy", processed_at__isnull=False).count() == 0
        finally:
            release.set()
        assert busy.result(timeout=5) == 1
    assert sync_pending(repository) == 1
    assert calls[-2:] == [("a-busy", "a-busy"), ("a-busy", "Later state")]


@pytest.mark.django_db(transaction=True)
def test_upgrade_populates_locks_without_losing_existing_outbox():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    old_target = [("catalog", "0002_alter_movie_id_alter_outboxevent_movie_id")]
    new_target = [("catalog", "0004_interactionevent_interaction_kind_time_idx_and_more")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        event = old_apps.get_model("catalog", "OutboxEvent").objects.create(
            movie_id="legacy-upgrade", operation="delete", payload={}
        )
        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        from cinegraph.catalog.models import MovieProjectionLock

        assert MovieProjectionLock.objects.filter(movie_id="legacy-upgrade").exists()
        assert OutboxEvent.objects.get(pk=event.pk).operation == "delete"
    finally:
        MigrationExecutor(connection).migrate(new_target)


@pytest.mark.django_db(transaction=True)
def test_watch_recovers_transient_heartbeat_database_failure(monkeypatch, capsys):
    import signal

    from django.db import DatabaseError

    from cinegraph.catalog.management.commands import sync_graph

    writes = []

    def unreliable_heartbeat(worker, status="running", error_code=""):
        writes.append((status, error_code))
        if len(writes) <= 2:
            raise DatabaseError("postgresql://user:secret-canary@unavailable/db")

    repository = Mock()
    repository.ensure_schema.side_effect = lambda: signal.raise_signal(signal.SIGTERM)
    close_connections = Mock(wraps=sync_graph.close_old_connections)
    monkeypatch.setattr(sync_graph, "close_old_connections", close_connections)
    monkeypatch.setattr(sync_graph, "heartbeat", unreliable_heartbeat)
    monkeypatch.setattr(sync_graph, "GraphRepository", lambda: repository)
    call_command("sync_graph", watch=True, interval=0.001, worker_name="recover-heartbeat")
    assert len(writes) >= 3
    assert writes[-1][0] == "stopped"
    assert close_connections.call_count >= 3
    assert "secret-canary" not in capsys.readouterr().err
    repository.close.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_final_heartbeat_failure_does_not_prevent_cleanup(monkeypatch, capsys):
    import signal

    from django.db import DatabaseError

    from cinegraph.catalog.management.commands import sync_graph

    def heartbeat_fails_on_shutdown(worker, status="running", error_code=""):
        if status == "stopped":
            raise DatabaseError("shutdown-secret-canary")

    repository = Mock()
    repository.ensure_schema.side_effect = lambda: signal.raise_signal(signal.SIGTERM)
    monkeypatch.setattr(sync_graph, "heartbeat", heartbeat_fails_on_shutdown)
    monkeypatch.setattr(sync_graph, "GraphRepository", lambda: repository)
    previous = signal.getsignal(signal.SIGTERM)
    call_command("sync_graph", watch=True, worker_name="shutdown-heartbeat")
    repository.close.assert_called_once()
    assert signal.getsignal(signal.SIGTERM) == previous
    assert "shutdown-secret-canary" not in capsys.readouterr().err
