from datetime import date

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate

from .models import DailyMetric, InteractionEvent

KINDS = ("search", "recommendation", "chat")


def record_event(kind: str):
    if kind not in KINDS:
        raise ValueError("Unknown interaction kind")
    InteractionEvent.objects.create(kind=kind)


def report(start: date | None = None, end: date | None = None) -> dict:
    """Read current events so dashboard reports never depend on a batch job."""
    if start and end and start > end:
        raise ValueError("start must not be after end")
    events = InteractionEvent.objects.all()
    if start:
        events = events.filter(created_at__date__gte=start)
    if end:
        events = events.filter(created_at__date__lte=end)
    rows = (
        events.annotate(day=TruncDate("created_at"))
        .values("day", "kind")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    daily = {}
    totals = dict.fromkeys(KINDS, 0)
    for row in rows:
        day = row["day"].isoformat()
        daily.setdefault(day, {"date": day, **dict.fromkeys(KINDS, 0)})
        daily[day][row["kind"]] += row["count"]
        totals[row["kind"]] += row["count"]
    return {"daily": list(daily.values()), "totals": totals}


@transaction.atomic
def aggregate():
    data = report()
    days = []
    for row in data["daily"]:
        day = row["date"]
        days.append(day)
        DailyMetric.objects.update_or_create(date=day, defaults={kind: row[kind] for kind in KINDS})
    DailyMetric.objects.exclude(date__in=days).delete()
    return len(days)
