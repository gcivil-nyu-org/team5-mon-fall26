from django.contrib import admin

from .models import Zone


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """US39 #113: staff can list and view the rows but not add, change or
    delete them (also no "Delete selected" action). Used for zones and,
    in US40, the import history."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Zone)
class ZoneAdmin(ReadOnlyModelAdmin):
    """US39 #113: read-only for now; US42 makes the names editable."""

    list_display = ("zone_id", "name", "borough")
    list_filter = ("borough",)
    search_fields = ("name",)
