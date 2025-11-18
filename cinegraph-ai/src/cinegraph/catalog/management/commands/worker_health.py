import os
import socket
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cinegraph.catalog.models import WorkerHeartbeat


class Command(BaseCommand):
    help = "Exit nonzero when this worker's heartbeat is absent, stopped or stale."

    def add_arguments(self, parser):
        parser.add_argument("--worker-name", default=os.getenv("CINEGRAPH_WORKER_NAME", socket.gethostname()))
        parser.add_argument("--max-age", type=int, default=90)

    def handle(self, *args, **options):
        if options["max_age"] <= 0:
            raise CommandError("Maximum heartbeat age must be positive")
        healthy = WorkerHeartbeat.objects.filter(
            worker_name=options["worker_name"],
            status="running",
            last_seen__gte=timezone.now() - timedelta(seconds=options["max_age"]),
        ).exists()
        if not healthy:
            raise CommandError("Worker heartbeat is absent, stopped or stale")
        self.stdout.write("Worker heartbeat healthy")
