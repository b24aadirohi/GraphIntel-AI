import os
import signal
import socket
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from cinegraph.catalog.models import OutboxEvent
from cinegraph.catalog.projection import eligible_events, heartbeat, safe_error, sync_pending
from cinegraph.shared.graph import GraphRepository


class Command(BaseCommand):
    help = "Project per-movie ordered SQL outbox events with bounded retries and graceful shutdown."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=float, default=2)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--worker-name", default=os.getenv("CINEGRAPH_WORKER_NAME", socket.gethostname()))

    def handle(self, *args, **options):
        if not 0 < options["interval"] <= 30 or options["batch_size"] <= 0:
            raise CommandError("Interval must be between 0 and 30 seconds and batch size must be positive")
        if not options["worker_name"] or len(options["worker_name"]) > 128:
            raise CommandError("Worker name must contain 1–128 characters")
        stop = threading.Event()
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        repository = None
        worker = options["worker_name"]
        delay = options["interval"]

        def best_effort_heartbeat(status="running", error_code=""):
            try:
                heartbeat(worker, status=status, error_code=error_code)
            except DatabaseError:
                self.stderr.write("Worker heartbeat unavailable: sql_unavailable")

        try:
            while not stop.is_set():
                try:
                    close_old_connections()
                    heartbeat(worker)
                    if repository is None:
                        repository = GraphRepository()
                    repository.ensure_schema()
                    count = sync_pending(repository, options["batch_size"], worker, stop.is_set)
                    self.stdout.write(f"Projected {count} events")
                    heartbeat(worker)
                    delay = options["interval"]
                    if stop.is_set():
                        break
                    if count and eligible_events().exists():
                        continue
                    if not options["watch"]:
                        if OutboxEvent.objects.filter(processed_at__isnull=True).exists():
                            raise CommandError(
                                "Projection backlog remains; inspect outbox retries and dead letters"
                            )
                        return
                except CommandError:
                    raise
                except Exception as exc:
                    code, message = safe_error(exc)
                    close_old_connections()
                    best_effort_heartbeat(error_code=code)
                    if not options["watch"]:
                        raise CommandError(message) from None
                    self.stderr.write(f"Graph worker retry: {code}")
                    delay = min(delay * 2, 30)
                stop.wait(delay)
        finally:
            try:
                close_old_connections()
                best_effort_heartbeat(status="stopped")
            finally:
                try:
                    if repository is not None:
                        repository.close()
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)
                    close_old_connections()
