"""US30 #92: Choose a Display Name."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse, reverse_lazy
from django.utils.http import urlencode

from accounts.display_name import display_name_of, display_name_required
from accounts.forms import (
    NAME_CONTAINS_EMAIL,
    NAME_IS_EMAIL_START,
    NAME_NEEDS_LETTER,
    NAME_OTHER_CHARACTERS,
    NAME_REQUIRED,
    NAME_RESERVED,
    NAME_TAKEN,
    NAME_TOO_LONG,
    NAME_TOO_SHORT,
    DisplayNameForm,
)
from accounts.models import Profile

User = get_user_model()

PASSWORD = "taxi-route-7319"


def make_user(email):
    return User.objects.create_user(email, email, PASSWORD)


class DisplayNameFormTests(TestCase):
    """The rules: 3 to 30 characters, letters, numbers, spaces, dots, dashes
    and underscores, unique ignoring capitals, no email address."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("alex.k@example.com")
        cls.other = make_user("sam@example.com")

    def errors_for(self, name, user=None):
        form = DisplayNameForm(user or self.user, {"display_name": name})
        self.assertFalse(form.is_valid())
        return form.errors["display_name"]

    def cleaned(self, name):
        form = DisplayNameForm(self.user, {"display_name": name})
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data["display_name"]

    def test_letters_numbers_spaces_dots_dashes_and_underscores_are_allowed(self):
        for name in ("Alex", "Rider 42", "a_b-c.d", "J. Doe", "abc", "x" * 30):
            with self.subTest(name=name):
                self.assertEqual(self.cleaned(name), name)

    def test_spaces_are_trimmed_and_runs_of_spaces_become_one(self):
        self.assertEqual(self.cleaned("   Alex    Rider  "), "Alex Rider")

    def test_a_name_is_required(self):
        for name in ("", "    "):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_REQUIRED])

    def test_too_short_is_rejected(self):
        for name in ("Al", "  Al  ", "a"):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_TOO_SHORT])

    def test_too_long_is_rejected(self):
        self.assertEqual(self.errors_for("x" * 31), [NAME_TOO_LONG])

    def test_thirty_characters_after_trimming_is_allowed(self):
        self.assertEqual(self.cleaned("  " + "x" * 30 + "  "), "x" * 30)

    def test_other_characters_are_rejected(self):
        # Accented and non-Latin letters too: "Аlex" starts with a Cyrillic А,
        # which would look exactly like another rider's "Alex".
        for name in ("Alex!", "Zoë", "Аlex", "Alex\tK", "Al<b>", "50%", "名前です"):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_OTHER_CHARACTERS])

    def test_an_email_address_is_rejected(self):
        for name in ("alex@example.com", "me@x", "hi @ there"):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_CONTAINS_EMAIL])

    def test_the_start_of_the_users_own_email_is_rejected(self):
        self.assertEqual(self.errors_for("Alex.K"), [NAME_IS_EMAIL_START])
        # Someone else may use it: it is not their email.
        form = DisplayNameForm(self.other, {"display_name": "alex.k"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_name_needs_a_letter_or_number(self):
        for name in ("...", "_-_", "- . -"):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_NEEDS_LETTER])

    def test_reserved_names_are_rejected_whatever_the_capitals(self):
        for name in ("admin", "Moderator", "TaxiScope", "taxiscope  NYC", "SUPPORT"):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_RESERVED])

    def test_a_name_taken_by_someone_else_is_rejected_whatever_the_capitals(self):
        Profile.objects.create(user=self.other, display_name="Alex")
        for name in ("Alex", "alex", "ALEX", "  aLeX "):
            with self.subTest(name=name):
                self.assertEqual(self.errors_for(name), [NAME_TAKEN])

    def test_the_users_own_name_in_new_capitals_is_allowed(self):
        Profile.objects.create(user=self.user, display_name="Rider")
        self.assertEqual(self.cleaned("RIDER"), "RIDER")

    def test_the_field_shows_the_current_name(self):
        Profile.objects.create(user=self.user, display_name="Rider")
        form = DisplayNameForm(self.user)
        self.assertEqual(form["display_name"].value(), "Rider")
        self.assertEqual(form.fields["display_name"].widget.attrs["maxlength"], "30")

    def test_save_creates_then_updates_one_profile(self):
        form = DisplayNameForm(self.user, {"display_name": "Rider"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().display_name, "Rider")

        form = DisplayNameForm(self.user, {"display_name": "Rider Two"})
        self.assertTrue(form.is_valid())
        form.save()

        self.assertEqual(Profile.objects.get(user=self.user).display_name, "Rider Two")
        self.assertEqual(Profile.objects.count(), 1)

    def test_a_name_taken_between_checking_and_saving_is_rejected(self):
        form = DisplayNameForm(self.user, {"display_name": "Alex"})
        self.assertTrue(form.is_valid())
        Profile.objects.create(user=self.other, display_name="alex")  # meanwhile

        self.assertIsNone(form.save())

        self.assertEqual(form.errors["display_name"], [NAME_TAKEN])
        self.assertFalse(Profile.objects.filter(user=self.user).exists())


class DisplayNameConstraintTests(TestCase):
    """The database refuses two names that differ only in capitals, so two
    people saving the same name at the same moment can't both succeed."""

    def test_same_name_in_other_capitals_is_refused_by_the_database(self):
        Profile.objects.create(user=make_user("a@example.com"), display_name="Alex")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Profile.objects.create(user=make_user("b@example.com"), display_name="aLEX")

    def test_one_profile_per_user(self):
        user = make_user("a@example.com")
        Profile.objects.create(user=user, display_name="Alex")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Profile.objects.create(user=user, display_name="Sam")

    def test_deleting_the_account_deletes_the_display_name(self):
        user = make_user("a@example.com")
        Profile.objects.create(user=user, display_name="Alex")

        user.delete()

        self.assertFalse(Profile.objects.exists())

    def test_profile_text_is_the_display_name(self):
        user = make_user("a@example.com")
        self.assertEqual(str(Profile(user=user, display_name="Alex")), "Alex")

    def test_profiles_are_in_the_admin(self):
        self.assertTrue(admin.site.is_registered(Profile))


class DisplayNamePageTests(TestCase):
    """Set and change the name on My account, or on its own page when a
    ride-sharing feature sends the rider there first."""

    url = reverse_lazy("accounts:display_name")
    account_url = reverse_lazy("accounts:account")

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("alex@example.com")

    def setUp(self):
        self.client.force_login(self.user)

    def save(self, name, next_page=None):
        data = {"display_name": name}
        if next_page is not None:
            data["next"] = next_page
        return self.client.post(self.url, data)

    def test_my_account_asks_for_a_name_when_there_is_none(self):
        response = self.client.get(self.account_url)

        self.assertContains(response, "Display name")
        self.assertContains(response, "You haven't chosen a display name yet.")
        self.assertContains(response, f'action="{self.url}"')
        self.assertContains(response, 'name="display_name"')
        self.assertContains(response, f'name="next" value="{self.account_url}"')

    def test_set_the_name_from_my_account(self):
        response = self.save("Alex Rider", next_page=str(self.account_url))

        self.assertRedirects(response, self.account_url, fetch_redirect_response=False)
        self.assertEqual(self.user.profile.display_name, "Alex Rider")
        page = self.client.get(self.account_url)
        self.assertContains(page, "Your display name was saved.")
        self.assertContains(page, "Other riders see you as <strong>Alex Rider</strong>")
        self.assertContains(page, 'value="Alex Rider"')

    def test_change_the_name(self):
        self.save("Alex Rider")
        response = self.save("Night Owl", next_page=str(self.account_url))

        self.assertRedirects(response, self.account_url)
        self.assertEqual(Profile.objects.get(user=self.user).display_name, "Night Owl")
        self.assertEqual(Profile.objects.count(), 1)

    def test_a_rejected_name_shows_the_reason_and_saves_nothing(self):
        Profile.objects.create(user=make_user("sam@example.com"), display_name="Sam")

        response = self.save("sam", next_page=str(self.account_url))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, NAME_TAKEN)
        self.assertContains(response, f'name="next" value="{self.account_url}"')
        self.assertFalse(Profile.objects.filter(user=self.user).exists())

    def test_the_page_explains_who_sees_the_name(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Choose a display name")
        self.assertContains(response, "never see your email address")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_after_saving_the_rider_goes_back_to_where_they_were(self):
        next_page = "/rides/new/?from=161&to=237"
        page = self.client.get(self.url, {"next": next_page})
        self.assertContains(page, 'name="next" value="/rides/new/?from=161&amp;to=237"')

        response = self.save("Alex Rider", next_page=next_page)

        self.assertRedirects(response, next_page, fetch_redirect_response=False)

    def test_another_site_in_next_is_ignored(self):
        for next_page in ("https://evil.example/", "//evil.example/", ""):
            with self.subTest(next_page=next_page):
                response = self.save("Alex Rider", next_page=next_page)

                self.assertRedirects(response, self.account_url)

    def test_without_next_the_rider_goes_to_my_account(self):
        self.assertRedirects(self.save("Alex Rider"), self.account_url)

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:signin')}?next={self.url}")

    def test_only_get_and_post(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    def test_saving_without_a_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(self.url, {"display_name": "Alex Rider"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Profile.objects.exists())

    def test_the_password_form_still_works_next_to_it(self):
        response = self.client.post(
            self.account_url,
            {
                "old_password": PASSWORD,
                "new_password1": "harbor-lights-5820",
                "new_password2": "harbor-lights-5820",
            },
        )

        self.assertRedirects(response, self.account_url)


def show_view(request):
    return HttpResponse("ride-sharing page")


class DisplayNameRequiredTests(TestCase):
    """Ride-sharing views (post, show interest, message) use
    @display_name_required: a rider without a name chooses one first, then
    comes back to the same page."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user("alex@example.com")

    def request(self, user, path="/rides/new/?from=161&to=237"):
        request = RequestFactory().get(path)
        request.user = user
        return display_name_required(show_view)(request)

    def test_a_rider_without_a_name_chooses_one_first(self):
        response = self.request(self.user)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('accounts:display_name')}?"
            + urlencode({"next": "/rides/new/?from=161&to=237"}),
        )

    def test_a_rider_with_a_name_goes_straight_in(self):
        Profile.objects.create(user=self.user, display_name="Alex Rider")

        response = self.request(self.user)

        self.assertContains(response, "ride-sharing page")

    def test_guests_are_left_to_the_view(self):
        # The view shows guests its own sign-in prompt (or uses @login_required).
        self.assertContains(self.request(AnonymousUser()), "ride-sharing page")

    def test_display_name_of(self):
        self.assertIsNone(display_name_of(self.user))
        self.assertIsNone(display_name_of(AnonymousUser()))
        Profile.objects.create(user=self.user, display_name="Alex Rider")
        self.user.refresh_from_db()
        self.assertEqual(display_name_of(self.user), "Alex Rider")
