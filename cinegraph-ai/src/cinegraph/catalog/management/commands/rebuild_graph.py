from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cinegraph.catalog.models import Movie, MovieProjectionLock, OutboxEvent
from cinegraph.shared.graph import GraphRepository


class Command(BaseCommand):
    help = "Queue all current SQL movies for an EMPTY graph; preserve existing pending updates and deletes."

    def handle(self, *args, **options):
        repository = GraphRepository()
        try:
            repository.ensure_schema()
            if repository.stats()["movies"]:
                raise CommandError(
                    "Rebuild requires an empty graph; restore into a separate empty database first"
                )
            # SQL movie locks serialize snapshots with edits/deletes; existing
            # outbox records remain ahead of rebuild snapshots. Concurrent new
            # movies create their own events, so no catalog write is lost.
            with transaction.atomic():
                count = 0
                for movie in Movie.objects.select_for_update().order_by("id").iterator():
                    MovieProjectionLock.objects.get_or_create(movie_id=movie.pk)
                    OutboxEvent.objects.create(movie_id=movie.pk, operation="upsert", payload=movie.as_dict())
                    count += 1
            self.stdout.write(
                f"Queued {count} current movies. Run sync_graph; recover any dead letters first."
            )
        finally:
            repository.close()
