from django.contrib import admin
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.urls import path


def live(request):
    return JsonResponse({"status": "ok"})


def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return JsonResponse({"status": "unavailable"}, status=503)
        return JsonResponse({"status": "ok", "database": "ok"})
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("live/", live),
    path("ready/", ready),
    path("health/", ready),
]
