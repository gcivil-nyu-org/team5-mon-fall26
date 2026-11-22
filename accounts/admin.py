from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .forms import StaffSignInForm
from .models import AccountAction, Profile
from . import restriction, suspension

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
        label="Reason",
        widget=forms.TextInput(attrs={"size": 45}),
    )
    # US47 #121: only for "Restrict"; the last restricted day (New York time).
    # Text, not a DateField: the admin skips the action without a message if
    # its form doesn't validate, so the action checks the date itself.
    restriction_end = forms.CharField(
        required=False,
        label="Restriction end date (optional)",
        widget=forms.DateInput(attrs={"type": "date"}),
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
        "restricted",
        "is_staff",
        "date_joined",
        "last_login",
    )
    action_form = AccountActionForm
    actions = (
        "suspend_accounts",
        "restore_accounts",
        "restrict_accounts",
        "lift_restrictions",
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

    def get_queryset(self, request):
        # US47 #121: the latest restrict or lift action, for the list column.
        latest = AccountAction.objects.filter(
            user=OuterRef("pk"),
            action__in=[AccountAction.RESTRICT, AccountAction.LIFT],
        ).order_by("-acted_at", "-pk")
        return (
            super()
            .get_queryset(request)
            .annotate(
                restriction_action=Subquery(latest.values("action")[:1]),
                restriction_ends_at=Subquery(latest.values("ends_at")[:1]),
            )
        )

    @admin.display(description="Restricted")
    def restricted(self, user):
        if getattr(user, "restriction_action", None) != AccountAction.RESTRICT:
            return "-"
        ends_at = user.restriction_ends_at
        if ends_at is None:
            return "Yes, no end date"
        if ends_at <= timezone.now():
            return "-"  # ended; recorded as lifted when the user next acts
        return f"Until {restriction.last_day(AccountAction(ends_at=ends_at)):%Y-%m-%d}"

    @admin.display(description="Suspension and restriction history")
    def account_history(self, user):
        lines = []
        for entry in user.account_actions.all():
            until = ""
            if entry.action == AccountAction.RESTRICT:
                end = restriction.last_day(entry)
                until = f" until {end:%Y-%m-%d}" if end else " (no end date)"
            lines.append(
                f"{entry.get_action_display()}{until}: {entry.reason} "
                f"({entry.acted_by}, "
                f"{timezone.localtime(entry.acted_at):%Y-%m-%d %H:%M})"
            )
        return "\n".join(lines) or "No suspension or restriction actions"

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

    # ---- US47 #121: restrict an account / lift a restriction ----

    def _restriction(self, request, queryset, change, done_text):
        reason = request.POST.get("reason", "").strip()
        if not reason:
            self.message_user(
                request,
                "Enter a reason before restricting or lifting.",
                messages.ERROR,
            )
            return
        changed = 0
        for user_id in queryset.values_list("pk", flat=True):
            done, detail = change(user_id, reason)
            if done:
                changed += 1
            else:
                self.message_user(request, detail, messages.WARNING)
        self.message_user(
            request, f"{changed} account(s) {done_text}.", messages.SUCCESS
        )

    @admin.action(description="Restrict selected accounts")
    def restrict_accounts(self, request, queryset):
        try:
            end = forms.DateField(required=False).clean(
                request.POST.get("restriction_end", "")
            )
        except forms.ValidationError:
            self.message_user(
                request, "Enter the end date as YYYY-MM-DD.", messages.ERROR
            )
            return
        self._restriction(
            request,
            queryset,
            lambda uid, reason: restriction.restrict(uid, request.user, reason, end),
            "restricted",
        )

    @admin.action(description="Lift restriction from selected accounts")
    def lift_restrictions(self, request, queryset):
        self._restriction(
            request,
            queryset,
            lambda uid, reason: restriction.lift(uid, request.user, reason),
            "lifted",
        )
