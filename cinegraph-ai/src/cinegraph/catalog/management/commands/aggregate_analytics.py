from django.core.management.base import BaseCommand

from cinegraph.catalog.analytics import aggregate


class Command(BaseCommand):
    help = "Refresh idempotent daily reporting tables from observed events."

    def handle(self, *args, **options):
        self.stdout.write(f"Aggregated {aggregate()} days")
