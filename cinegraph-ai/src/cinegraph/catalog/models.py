import re

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone


def validate_movie_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) or value in {".", ".."}:
        raise ValidationError(
            "Use 1–128 ASCII letters, digits, underscores, dots or hyphens; '.' and '..' are not valid identifiers."
        )


def validate_string_list(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("Expected a list of nonempty strings.")
    if len(value) > 100 or any(len(item) > 200 for item in value):
        raise ValidationError("At most 100 values of 200 characters are allowed.")


class Movie(models.Model):
    id = models.CharField(primary_key=True, max_length=128, validators=[validate_movie_id])
    title = models.CharField(max_length=250)
    released = models.PositiveIntegerField(validators=[MinValueValidator(1888), MaxValueValidator(2200)])
    summary = models.TextField(max_length=10000)
    genres = models.JSONField(default=list, blank=True, validators=[validate_string_list])
    cast = models.JSONField(default=list, blank=True, validators=[validate_string_list])
    directors = models.JSONField(default=list, blank=True, validators=[validate_string_list])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def as_dict(self):
        return {
            field: getattr(self, field)
            for field in ("id", "title", "released", "summary", "genres", "cast", "directors")
        }

    def save(self, *args, **kwargs):
        self.full_clean()
        using = kwargs.get("using") or self._state.db or "default"
        with transaction.atomic(using=using):
            super().save(*args, **kwargs)
            # Reload so update_fields produces the exact committed representation.
            payload = type(self).objects.using(using).get(pk=self.pk).as_dict()
            MovieProjectionLock.objects.using(using).get_or_create(movie_id=self.pk)
            OutboxEvent.objects.using(using).create(movie_id=self.pk, operation="upsert", payload=payload)


class OutboxEvent(models.Model):
    movie_id = models.CharField(max_length=128)
    operation = models.CharField(max_length=10, choices=[("upsert", "Upsert"), ("delete", "Delete")])
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["movie_id", "id"], name="outbox_movie_order_idx"),
            models.Index(
                fields=["next_attempt_at", "id"],
                condition=models.Q(processed_at__isnull=True, dead_lettered_at__isnull=True),
                name="outbox_due_pending_idx",
            ),
        ]


class MovieProjectionLock(models.Model):
    """Persistent per-movie synchronization fence, including deleted movies."""

    movie_id = models.CharField(primary_key=True, max_length=128)


class WorkerHeartbeat(models.Model):
    worker_name = models.CharField(primary_key=True, max_length=128)
    last_seen = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default="running")
    error_code = models.CharField(max_length=40, blank=True)


class InteractionEvent(models.Model):
    kind = models.CharField(
        max_length=20, choices=[("search", "Search"), ("recommendation", "Recommendation"), ("chat", "Chat")]
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["kind", "created_at"], name="interaction_kind_time_idx")]


class DailyMetric(models.Model):
    date = models.DateField(primary_key=True)
    search = models.PositiveIntegerField(default=0)
    recommendation = models.PositiveIntegerField(default=0)
    chat = models.PositiveIntegerField(default=0)
