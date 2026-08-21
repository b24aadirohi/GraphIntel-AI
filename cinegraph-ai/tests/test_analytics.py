from datetime import date, datetime, timezone

import pytest
from django.core.management import call_command

from cinegraph.catalog.analytics import record_event, report
from cinegraph.catalog.models import DailyMetric, InteractionEvent

pytestmark = pytest.mark.django_db


def test_empty_report():
    assert report() == {"daily": [], "totals": {"search": 0, "recommendation": 0, "chat": 0}}


def test_reporting_is_fresh_and_filtered():
    record_event("search")
    record_event("search")
    InteractionEvent.objects.update(created_at=datetime(2025, 1, 1, 12, tzinfo=timezone.utc))
    record_event("chat")
    InteractionEvent.objects.filter(kind="chat").update(
        created_at=datetime(2025, 1, 2, 12, tzinfo=timezone.utc)
    )
    record_event("recommendation")
    InteractionEvent.objects.filter(kind="recommendation").update(
        created_at=datetime(2025, 1, 2, 23, 59, tzinfo=timezone.utc)
    )
    assert not DailyMetric.objects.exists()
    result = report(date(2025, 1, 2), date(2025, 1, 2))
    assert result == {
        "daily": [{"date": "2025-01-02", "search": 0, "recommendation": 1, "chat": 1}],
        "totals": {"search": 0, "recommendation": 1, "chat": 1},
    }
    assert report()["totals"]["search"] == 2


def test_daily_aggregation_is_idempotent_and_refreshes():
    record_event("search")
    call_command("aggregate_analytics")
    call_command("aggregate_analytics")
    assert DailyMetric.objects.count() == 1
    assert DailyMetric.objects.get().search == 1
    record_event("search")
    call_command("aggregate_analytics")
    assert DailyMetric.objects.get().search == 2
    InteractionEvent.objects.all().delete()
    call_command("aggregate_analytics")
    assert not DailyMetric.objects.exists()


def test_invalid_analytics_input():
    with pytest.raises(ValueError):
        record_event("purchase")
    with pytest.raises(ValueError):
        report(date(2025, 2, 1), date(2025, 1, 1))
