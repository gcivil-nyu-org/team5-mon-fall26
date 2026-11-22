from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist

from .forms import StaffSignInForm
from .models import AccountAction, Profile
from . import suspension

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


class AccountActionForm(ActionForm):
    reason = forms.CharField(
        required=False,
        max_length=200,
        label="Reason for suspension or restoration",
        widget=forms.TextInput(attrs={"size": 45}),
    )


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
    action_form = AccountActionForm
    actions = ("suspend_accounts", "restore_accounts")
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "profile__display_name")
    list_select_related = ("profile",)
    ordering = ("email",)
    fields = (
        "email",
        "display_name",
        "date_joined",
        "last_login",
        "account_history",
        "is_staff",
        "is_superuser",
    )
    readonly_fields = (
        "email",
        "display_name",
        "date_joined",
        "last_login",
        "account_history",
        "is_active",
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

    @admin.display(description="Suspension history")
    def account_history(self, user):
        return (
            "\n".join(
                f"{entry.get_action_display()}: {entry.reason} "
                f"({entry.acted_by}, {entry.acted_at:%Y-%m-%d %H:%M})"
                for entry in user.account_actions.all()
            )
            or "No suspension actions"
        )

    def _change_accounts(self, request, queryset, action):
        reason = request.POST.get("reason", "").strip()
        if not reason:
            self.message_user(
                request, "Enter a reason before changing accounts.", messages.ERROR
            )
            return
        changed = 0
        for user_id in queryset.values_list("pk", flat=True):
            done, detail = suspension.change_account(
                user_id, request.user, action, reason
            )
            if done:
                changed += 1
            else:
                self.message_user(request, detail, messages.WARNING)
        verb = "suspended" if action == AccountAction.SUSPEND else "restored"
        self.message_user(request, f"{changed} account(s) {verb}.", messages.SUCCESS)

    @admin.action(description="Suspend selected accounts")
    def suspend_accounts(self, request, queryset):
        self._change_accounts(request, queryset, AccountAction.SUSPEND)

    @admin.action(description="Restore selected accounts")
    def restore_accounts(self, request, queryset):
        self._change_accounts(request, queryset, AccountAction.RESTORE)
