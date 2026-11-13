from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """US30 #92: an admin can rename an offensive display name here until
    Epic 5 adds proper moderation."""

    list_display = ("display_name", "user")
    search_fields = ("display_name",)
    raw_id_fields = ("user",)
