import json
from importlib.resources import files

from django.core.management.base import BaseCommand
from django.db import transaction

from cinegraph.catalog.models import Movie, OutboxEvent


class Command(BaseCommand):
    help = "Create missing sample movies, preserving existing catalog edits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-existing",
            action="store_true",
            help="Explicitly restore existing sample movies from fixtures",
        )
        parser.add_argument(
            "--requeue", action="store_true", help="Queue every movie again to rebuild an empty graph"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        movies = json.loads(files("cinegraph.catalog.data").joinpath("movies.json").read_text())
        changed = 0
        for payload in movies:
            movie, created = Movie.objects.get_or_create(
                pk=payload["id"], defaults={k: v for k, v in payload.items() if k != "id"}
            )
            if not created and options["reset_existing"] and movie.as_dict() != payload:
                for key, value in payload.items():
                    setattr(movie, key, value)
                movie.save()
                changed += 1
            elif created:
                changed += 1
        if options["requeue"]:
            for movie in Movie.objects.all().iterator():
                OutboxEvent.objects.create(movie_id=movie.pk, operation="upsert", payload=movie.as_dict())
        self.stdout.write(f"Sample catalog: {len(movies)} movies, {changed} changes")
