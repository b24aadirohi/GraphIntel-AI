from django.contrib import admin

from .models import DailyMetric, InteractionEvent, Movie, OutboxEvent

admin.site.site_header = "GraphIntel AI — Data Administration"
admin.site.site_title = "GraphIntel AI Admin"
admin.site.index_title = "Catalog, digital analytics and data operations"


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "released", "updated_at")
    search_fields = ("id", "title", "summary")
    list_filter = ("released",)
    readonly_fields = ("updated_at",)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("id",) if obj else ())


class AuditAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OutboxEvent)
class OutboxAdmin(AuditAdmin):
    list_display = (
        "id",
        "movie_id",
        "operation",
        "created_at",
        "processed_at",
        "attempts",
        "dead_lettered_at",
        "next_attempt_at",
        "error_code",
    )
    list_filter = ("operation", "processed_at", "dead_lettered_at", "error_code")
    search_fields = ("movie_id", "last_error")


admin.site.register(InteractionEvent, AuditAdmin)
admin.site.register(DailyMetric, AuditAdmin)
