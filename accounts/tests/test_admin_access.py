"""US39 #113: Admin Access and Staff Accounts.

Only staff accounts reach the Django admin at /admin/. Riders and guests
get the admin sign-in page (or a 403) on every admin URL, and the "Admin"
link in the site header shows for staff only."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import URLPattern, reverse

from accounts.models import Profile
from zones.models import CleaningRules, ImportRun, Zone

User = get_user_model()

PASSWORD = "taxi-route-7319"
ADMIN_LOGIN = reverse("admin:login")
STAFF_ERROR = "Enter the email and password of a staff account."

# Site-level admin URLs a non-staff user may open: the sign-in page itself
# and sign-out (which only ends a session).
OPEN_TO_EVERYONE = {"login", "logout"}


def site_level_urls():
    """(name, url) for every named admin URL that isn't a model page."""
    urls = []
    for pattern in admin.site.get_urls():
        if not isinstance(pattern, URLPattern) or not pattern.name:
            continue  # model pages are checked by model_urls()
        if pattern.name in OPEN_TO_EVERYONE:
            continue
        if pattern.name == "app_list":
            for app_label in {m._meta.app_label for m in admin.site._registry}:
                urls.append(
                    (
                        f"app_list {app_label}",
                        reverse("admin:app_list", args=[app_label]),
                    )
                )
        elif pattern.name == "view_on_site":
            urls.append((pattern.name, reverse("admin:view_on_site", args=[1, 1])))
        else:
            urls.append((pattern.name, reverse(f"admin:{pattern.name}")))
    return urls


def model_urls():
    """(name, url) for every named page of every registered model (list,
    add, change, delete, history), with a real object id where one
    exists."""
    urls = []
    for model, model_admin in admin.site._registry.items():
        obj = model._default_manager.first()
        object_id = obj.pk if obj else 1
        for pattern in model_admin.get_urls():
            if not pattern.name:
                continue  # the unnamed catch-all just redirects to "change"
            kwargs = {}
            if "object_id" in pattern.pattern.converters:
                kwargs["object_id"] = object_id
            urls.append((pattern.name, reverse(f"admin:{pattern.name}", kwargs=kwargs)))
    return urls


class AdminData:
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            "staff@example.com", "staff@example.com", PASSWORD
        )
        cls.rider = User.objects.create_user(
            "rider@example.com", "rider@example.com", PASSWORD
        )
        Profile.objects.create(user=cls.rider, display_name="Rider One")
        Zone.objects.create(zone_id=132, name="JFK Airport", borough="Queens")


class StaffSignInTests(AdminData, TestCase):
    """AC1: a staff account can sign in to /admin/."""

    def sign_in(self, email, password=PASSWORD):
        return self.client.post(
            ADMIN_LOGIN,
            {"username": email, "password": password, "next": "/admin/"},
        )

    def test_admin_is_at_slash_admin(self):
        self.assertEqual(reverse("admin:index"), "/admin/")

    def test_staff_signs_in_and_sees_the_admin(self):
        response = self.sign_in("staff@example.com")

        self.assertRedirects(response, "/admin/")
        page = self.client.get("/admin/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "TaxiScope NYC admin")
        self.assertContains(page, "Zones")

    def test_sign_in_page_asks_for_the_email(self):
        response = self.client.get(ADMIN_LOGIN)

        self.assertContains(response, "Email")

    def test_email_is_not_case_sensitive(self):
        response = self.sign_in("  Staff@Example.COM ")

        self.assertRedirects(response, "/admin/")

    def test_wrong_password_does_not_sign_in(self):
        response = self.sign_in("staff@example.com", "not-the-password")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, STAFF_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_rider_cannot_sign_in_to_the_admin(self):
        response = self.sign_in("rider@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, STAFF_ERROR)
        self.assertNotContains(response, "case-sensitive")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_staff_cannot_sign_in(self):
        self.staff.is_active = False
        self.staff.save()

        response = self.sign_in("staff@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_signs_in_with_the_site_sign_in_too(self):
        self.client.post(
            reverse("accounts:signin"),
            {"username": "staff@example.com", "password": PASSWORD},
        )

        self.assertEqual(self.client.get("/admin/").status_code, 200)


class NonStaffRefusedTests(AdminData, TestCase):
    """AC2: a rider (and a guest) cannot open any admin page. They get the
    admin sign-in page or a 403, for GET and POST alike."""

    def all_admin_urls(self):
        urls = site_level_urls() + model_urls()
        urls.append(("catch-all", "/admin/no-such-page/"))
        return urls

    def assert_refused(self, response, name, url):
        if response.status_code == 403:
            return
        self.assertEqual(response.status_code, 302, f"{name} {url}")
        self.assertTrue(response["Location"].startswith(ADMIN_LOGIN), f"{name} {url}")

    def test_every_registered_model_has_pages_to_check(self):
        names = {name for name, _ in model_urls()}

        for model in (User, Profile, Zone, ImportRun, CleaningRules):
            label = f"{model._meta.app_label}_{model._meta.model_name}"
            self.assertIn(f"{label}_changelist", names)
            self.assertIn(f"{label}_change", names)

    def test_guest_is_refused_everywhere(self):
        for name, url in self.all_admin_urls():
            with self.subTest(name=name):
                self.assert_refused(self.client.get(url), name, url)
                self.assert_refused(self.client.post(url, {}), name, url)

    def test_signed_in_rider_is_refused_everywhere(self):
        self.client.force_login(self.rider)

        for name, url in self.all_admin_urls():
            with self.subTest(name=name):
                self.assert_refused(self.client.get(url), name, url)
                self.assert_refused(self.client.post(url, {}), name, url)

    def test_inactive_staff_is_refused(self):
        self.staff.is_active = False
        self.staff.save()
        self.client.force_login(self.staff)

        self.assert_refused(self.client.get("/admin/"), "index", "/admin/")

    def test_rider_cannot_run_an_admin_action(self):
        self.client.force_login(self.rider)

        response = self.client.post(
            reverse("admin:auth_user_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [self.staff.pk, self.rider.pk],
                "post": "yes",
            },
        )

        self.assert_refused(response, "delete_selected", "auth_user_changelist")
        self.assertEqual(User.objects.count(), 2)

    def test_rider_cannot_make_themselves_staff(self):
        self.client.force_login(self.rider)

        self.client.post(
            reverse("admin:auth_user_change", args=[self.rider.pk]),
            {"is_active": "on", "is_staff": "on", "is_superuser": "on"},
        )

        self.rider.refresh_from_db()
        self.assertFalse(self.rider.is_staff)
        self.assertFalse(self.rider.is_superuser)

    def test_rider_is_shown_the_admin_sign_in_page(self):
        self.client.force_login(self.rider)

        response = self.client.get("/admin/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not authorized to access this page")

    def test_staff_without_superuser_rights_cannot_open_model_pages(self):
        helper = User.objects.create_user(
            "helper@example.com", "helper@example.com", PASSWORD, is_staff=True
        )
        self.client.force_login(helper)

        response = self.client.get(reverse("admin:auth_user_changelist"))

        self.assertEqual(response.status_code, 403)


class AdminLinkTests(AdminData, TestCase):
    """AC3: the "Admin" link in the site header shows for staff only."""

    LINK = 'href="/admin/"'

    def header_pages(self):
        return [
            reverse("zones:map"),
            reverse("zones:compare"),
            reverse("routes:my_routes"),
            reverse("accounts:account"),
        ]

    def test_staff_see_the_admin_link_on_every_header(self):
        self.client.force_login(self.staff)

        for url in self.header_pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.LINK, count=1)
                self.assertContains(response, ">Admin</a>")

    def test_riders_do_not_see_the_admin_link(self):
        self.client.force_login(self.rider)

        for url in self.header_pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.LINK)
                self.assertNotContains(response, ">Admin</a>")

    def test_guests_do_not_see_the_admin_link(self):
        for url in (reverse("zones:map"), reverse("zones:compare")):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), self.LINK)


class UserAdminTests(AdminData, TestCase):
    """Staff see only what they need about an account: no password hash,
    no password reset, and staff rights change only through the
    create_staff and remove_staff commands."""

    def setUp(self):
        self.client.force_login(self.staff)

    def test_user_list_shows_email_and_display_name(self):
        response = self.client.get(reverse("admin:auth_user_changelist"))

        self.assertContains(response, "rider@example.com")
        self.assertContains(response, "Rider One")

    def test_search_by_email_or_display_name(self):
        url = reverse("admin:auth_user_changelist")

        by_email = self.client.get(url, {"q": "rider@"})
        by_name = self.client.get(url, {"q": "Rider One"})

        for response in (by_email, by_name):
            self.assertEqual(response.context["cl"].result_count, 1)

    def test_change_page_never_shows_the_password(self):
        response = self.client.get(
            reverse("admin:auth_user_change", args=[self.rider.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "rider@example.com")
        self.assertNotContains(response, self.rider.password)
        self.assertNotContains(response, "pbkdf2")
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, "Reset password")

    def test_there_is_no_password_reset_page(self):
        self.assertFalse(
            any(
                "password" in str(p.pattern)
                for p in admin.site._registry[User].get_urls()
            )
        )

    def test_staff_rights_cannot_be_changed_in_the_admin(self):
        response = self.client.post(
            reverse("admin:auth_user_change", args=[self.rider.pk]),
            {
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "email": "changed@example.com",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.rider.refresh_from_db()
        self.assertFalse(self.rider.is_staff)
        self.assertFalse(self.rider.is_superuser)
        self.assertEqual(self.rider.email, "rider@example.com")

    def test_staff_can_deactivate_an_account(self):
        response = self.client.post(
            reverse("admin:auth_user_change", args=[self.rider.pk]), {}
        )

        self.assertEqual(response.status_code, 302)
        self.rider.refresh_from_db()
        self.assertFalse(self.rider.is_active)

    def test_accounts_cannot_be_added_in_the_admin(self):
        response = self.client.get(reverse("admin:auth_user_add"))

        self.assertEqual(response.status_code, 403)

    def test_staff_can_delete_an_account(self):
        response = self.client.post(
            reverse("admin:auth_user_delete", args=[self.rider.pk]),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.rider.pk).exists())
        self.assertFalse(Profile.objects.exists())

    def test_account_without_a_display_name_shows_a_dash(self):
        model_admin = admin.site._registry[User]

        self.assertEqual(model_admin.display_name(self.staff), "-")
        self.assertEqual(model_admin.display_name(self.rider), "Rider One")

    def test_groups_are_not_in_the_admin(self):
        self.assertFalse(admin.site.is_registered(Group))
