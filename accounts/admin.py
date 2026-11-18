from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist

from .forms import StaffSignInForm
from .models import Profile

User = get_user_model()

# US39 #113: the admin at /admin/ is for staff accounts only (is_active and
# is_staff, checked by Django on every admin page). Staff accounts are made
# with `manage.py create_staff` and removed with `manage.py remove_staff`.
admin.site.site_header = "TaxiScope NYC admin"
admin.site.site_title = "TaxiScope NYC admin"
admin.site.index_title = "Manage data and content"
admin.site.login_form = StaffSignInForm

# Staff accounts are superusers, so groups and per-model permissions are not
# used.
admin.site.unregister(Group)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """US30 #92: an admin can rename an offensive display name here until
    Epic 5 adds proper moderation."""

    list_display = ("display_name", "user")
    search_fields = ("display_name",)
    raw_id_fields = ("user",)


admin.site.unregister(User)


@admin.register(User)
class AccountAdmin(admin.ModelAdmin):
    """US39 #113: accounts, showing only what staff need. Never the password
    or its hash, and no password reset (riders change their own password,
    US12). Staff rights are read-only here: they change only through the
    create_staff and remove_staff commands. Staff can deactivate or delete
    an account; accounts are added by signing up, not here."""

    list_display = (
        "email",
        "display_name",
        "is_active",
        "is_staff",
        "date_joined",
        "last_login",
    )
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "profile__display_name")
    list_select_related = ("profile",)
    ordering = ("email",)
    fields = (
        "email",
        "display_name",
        "date_joined",
        "last_login",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    readonly_fields = (
        "email",
        "display_name",
        "date_joined",
        "last_login",
        "is_staff",
        "is_superuser",
    )

    @admin.display(description="Display name")
    def display_name(self, user):
        try:
            return user.profile.display_name
        except ObjectDoesNotExist:
            return "-"

    def has_add_permission(self, request):
        return False
