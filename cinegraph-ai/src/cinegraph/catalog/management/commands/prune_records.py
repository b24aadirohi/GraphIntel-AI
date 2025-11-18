from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cinegraph.catalog.models import InteractionEvent, OutboxEvent


class Command(BaseCommand):
    help = "Prune only old processed outbox entries and interaction events, using explicit retention ages."

    def add_arguments(self, parser):
        parser.add_argument("--processed-days", type=int, required=True)
        parser.add_argument("--event-days", type=int, required=True)
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if min(options["processed_days"], options["event_days"], options["batch_size"]) <= 0:
            raise CommandError("Retention ages and batch size must be positive")
        now = timezone.now()
        targets = [
            (
                "processed_outbox",
                OutboxEvent.objects.filter(
                    processed_at__lt=now - timedelta(days=options["processed_days"]),
                    dead_lettered_at__isnull=True,
                ),
            ),
            (
                "interaction_events",
                InteractionEvent.objects.filter(created_at__lt=now - timedelta(days=options["event_days"])),
            ),
        ]
        for label, queryset in targets:
            if options["dry_run"]:
                self.stdout.write(f"{label}: {queryset.count()} eligible (dry run)")
                continue
            count = 0
            while ids := list(queryset.values_list("pk", flat=True)[: options["batch_size"]]):
                deleted, _ = queryset.filter(pk__in=ids).delete()
                count += deleted
            self.stdout.write(f"{label}: {count} removed")
