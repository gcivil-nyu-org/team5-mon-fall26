"""US10 #39: Sign Up."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from accounts.forms import SignUpForm

User = get_user_model()

GOOD_PASSWORD = "taxi-route-7319"


def form_data(email="alex@example.com", password=GOOD_PASSWORD, confirm=None):
    return {
        "email": email,
        "password1": password,
        "password2": password if confirm is None else confirm,
    }


class SignUpFormTests(TestCase):
    """The form checks the email and the password."""

    def test_valid_data_creates_user_with_email_as_username(self):
        form = SignUpForm(data=form_data())

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, "alex@example.com")
        self.assertEqual(user.email, "alex@example.com")
        self.assertTrue(user.check_password(GOOD_PASSWORD))

    def test_email_is_stored_lowercase_and_trimmed(self):
        form = SignUpForm(data=form_data(email="  Alex@Example.COM "))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().username, "alex@example.com")

    def test_registered_email_is_rejected_with_clear_message(self):
        User.objects.create_user("alex@example.com", "alex@example.com", "x")

        form = SignUpForm(data=form_data(email="ALEX@example.com"))

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["email"], ["An account with this email already exists."]
        )

    def test_invalid_email_is_rejected(self):
        form = SignUpForm(data=form_data(email="not-an-email"))

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_weak_passwords_are_rejected_with_the_reason(self):
        cases = {
            "short": "too short",
            "password123": "too common",
            "48201937564": "entirely numeric",
            "alex@example.com": "too similar",
        }
        for password, reason in cases.items():
            with self.subTest(password=password):
                form = SignUpForm(data=form_data(password=password))

                self.assertFalse(form.is_valid())
                self.assertIn(reason, " ".join(form.errors["password1"]))

    def test_passwords_must_match(self):
        form = SignUpForm(data=form_data(confirm="something-else-42"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["password2"], ["The two passwords do not match."])

    def test_all_fields_required(self):
        form = SignUpForm(data={})

        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {"email", "password1", "password2"})


class SignUpViewTests(TestCase):
    """GET and POST /accounts/signup/."""

    url = reverse("accounts:signup")

    def test_page_shows_the_form_with_csrf(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_sign_up_signs_in_and_returns_to_the_map(self):
        response = self.client.post(self.url, form_data())

        self.assertRedirects(response, reverse("zones:map"))
        user = User.objects.get(username="alex@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_registered_email_shows_message_and_creates_nothing(self):
        User.objects.create_user("alex@example.com", "alex@example.com", "x")

        response = self.client.post(self.url, form_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email already exists.")
        self.assertEqual(User.objects.count(), 1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_weak_password_shows_reason_and_creates_nothing(self):
        response = self.client.post(self.url, form_data(password="short"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "too short")
        self.assertFalse(User.objects.exists())

    def test_email_kept_in_form_after_an_error(self):
        response = self.client.post(self.url, form_data(password="short"))

        self.assertContains(response, 'value="alex@example.com"')

    def test_same_email_created_at_the_same_time_shows_message(self):
        # Another request can create the same email between the form check
        # and the insert; the unique username then raises IntegrityError.
        with mock.patch(
            "accounts.forms.User.objects.create_user", side_effect=IntegrityError
        ):
            response = self.client.post(self.url, form_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email already exists.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signed_in_user_is_sent_to_the_map(self):
        user = User.objects.create_user("alex@example.com", "alex@example.com", "x")
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("zones:map"))


class MapHeaderTests(TestCase):
    """The map header links to sign-up and never blocks the map (US9)."""

    def test_guest_sees_sign_up_link_and_the_map(self):
        response = self.client.get(reverse("zones:map"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("accounts:signup")}"')
        self.assertContains(response, '<div id="map">')

    def test_signed_in_user_sees_email_not_sign_up(self):
        user = User.objects.create_user("alex@example.com", "alex@example.com", "x")
        self.client.force_login(user)

        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, "alex@example.com")
        self.assertNotContains(response, f'href="{reverse("accounts:signup")}"')
        self.assertContains(response, '<div id="map">')

    def test_zones_api_still_works_without_an_account(self):
        response = self.client.get(reverse("zones:zones_api"), {"day": 0, "hour": 8})

        self.assertEqual(response.status_code, 200)
