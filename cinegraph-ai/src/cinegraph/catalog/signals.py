from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Movie, MovieProjectionLock, OutboxEvent


@receiver(post_delete, sender=Movie)
def queue_deleted_movie(sender, instance, using, **kwargs):
    MovieProjectionLock.objects.using(using).get_or_create(movie_id=instance.pk)
    OutboxEvent.objects.using(using).create(movie_id=instance.pk, operation="delete", payload={})
