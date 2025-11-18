from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from cinegraph.catalog.models import MovieProjectionLock, OutboxEvent


class Command(BaseCommand):
    help = "Explicitly reset dead-letter attempts while preserving original per-movie order."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--id", type=int)
        group.add_argument("--movie-id")

    def handle(self, *args, **options):
        selection = (
            {"pk": options["id"]} if options.get("id") is not None else {"movie_id": options["movie_id"]}
        )
        target = OutboxEvent.objects.filter(**selection).first()
        if target is None:
            raise CommandError("No matching outbox event")
        with transaction.atomic():
            MovieProjectionLock.objects.select_for_update().get(movie_id=target.movie_id)
            count = OutboxEvent.objects.filter(
                **selection, processed_at__isnull=True, dead_lettered_at__isnull=False
            ).update(
                attempts=0,
                dead_lettered_at=None,
                next_attempt_at=timezone.now(),
                error_code="",
                last_error="",
            )
        if not count:
            raise CommandError("No matching dead-letter event; pending delivery was not changed")
        self.stdout.write(f"Requeued {count} dead-letter events in original order")
