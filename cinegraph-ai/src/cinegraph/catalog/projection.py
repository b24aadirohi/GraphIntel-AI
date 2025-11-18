"""Per-movie ordered, at-least-once graph projection with bounded retries."""

from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.db.models import Exists, Min, OuterRef, Subquery
from django.utils import timezone

from .models import MovieProjectionLock, OutboxEvent, WorkerHeartbeat

MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 2
RETRY_MAX_SECONDS = 300


def safe_error(exc):
    """Only allowlisted codes/messages persist; exception text may contain secrets."""
    from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
    from pydantic import ValidationError

    if isinstance(exc, DatabaseError):
        return "sql_unavailable", "SQL service unavailable; worker will retry."
    if isinstance(exc, ValidationError):
        return "invalid_payload", "Movie payload validation failed."
    if isinstance(exc, (Neo4jError, ServiceUnavailable, SessionExpired)):
        return "graph_unavailable", "Graph operation failed; check graph connectivity and server logs."
    return "projection_failed", "Projection failed; inspect service configuration and graph availability."


def heartbeat(worker_name, status="running", error_code=""):
    WorkerHeartbeat.objects.update_or_create(
        worker_name=worker_name,
        defaults={"last_seen": timezone.now(), "status": status, "error_code": error_code},
    )


def projection_status():
    pending = OutboxEvent.objects.filter(processed_at__isnull=True)
    oldest = pending.aggregate(oldest=Min("created_at"))["oldest"]
    latest = WorkerHeartbeat.objects.filter(status="running").order_by("-last_seen").first()
    return {
        "backlog": pending.count(),
        "deadletters": pending.filter(dead_lettered_at__isnull=False).count(),
        "oldest_age_seconds": max(0, (timezone.now() - oldest).total_seconds()) if oldest else 0,
        "last_heartbeat": latest.last_seen.isoformat() if latest else None,
    }


def eligible_events():
    older = OutboxEvent.objects.filter(
        movie_id=OuterRef("movie_id"), processed_at__isnull=True, id__lt=OuterRef("id")
    )
    return (
        OutboxEvent.objects.filter(
            processed_at__isnull=True, dead_lettered_at__isnull=True, next_attempt_at__lte=timezone.now()
        )
        .annotate(has_older=Exists(older))
        .filter(has_older=False)
    )


def sync_pending(repository, limit=100, worker_name=None, should_stop=None):
    """Serialize only a movie's writes; locked movies are skipped by other workers.

    The per-movie lock remains held until graph write + SQL acknowledgement.
    Crashes can replay a write, but cannot reorder it. A dead-lettered event is
    retained as the movie's ordering barrier until explicitly retried.
    PostgreSQL is required for multiworker safety; SQLite is single-worker only.
    """
    processed = 0
    for _ in range(limit):
        if should_stop and should_stop():
            break
        if worker_name:
            heartbeat(worker_name)
        with transaction.atomic():
            locks = MovieProjectionLock.objects.filter(
                movie_id__in=Subquery(eligible_events().values("movie_id"))
            ).order_by("movie_id")
            if connection.features.has_select_for_update_skip_locked:
                locks = locks.select_for_update(skip_locked=True)
            else:
                locks = locks.select_for_update()
            lock = locks.first()
            if lock is None:
                break
            # Recheck under the movie lock: another worker may have completed
            # this event between candidate selection and lock acquisition.
            event = (
                OutboxEvent.objects.filter(movie_id=lock.movie_id, processed_at__isnull=True)
                .order_by("id")
                .first()
            )
            if event is None or event.dead_lettered_at or event.next_attempt_at > timezone.now():
                continue
            event.attempts += 1
            try:
                if event.operation == "delete":
                    repository.delete_movie(event.movie_id)
                else:
                    repository.upsert_movie(event.payload)
            except Exception as exc:
                event.error_code, event.last_error = safe_error(exc)
                if event.attempts >= MAX_ATTEMPTS:
                    event.dead_lettered_at = timezone.now()
                else:
                    delay = min(RETRY_BASE_SECONDS * 2 ** (event.attempts - 1), RETRY_MAX_SECONDS)
                    event.next_attempt_at = timezone.now() + timedelta(seconds=delay)
                event.save(
                    update_fields=[
                        "attempts",
                        "last_error",
                        "error_code",
                        "next_attempt_at",
                        "dead_lettered_at",
                    ]
                )
                continue
            event.processed_at = timezone.now()
            event.last_error = ""
            event.error_code = ""
            event.save(update_fields=["attempts", "processed_at", "last_error", "error_code"])
            processed += 1
    return processed
