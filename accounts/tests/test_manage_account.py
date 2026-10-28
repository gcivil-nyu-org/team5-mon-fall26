"""US12 #41: Manage and Delete My Account."""

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase
from django.urls import reverse, reverse_lazy

User = get_user_model()

PASSWORD = "taxi-route-7319"
NEW_PASSWORD = "harbor-lights-5820"


class AccountData:
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alex@example.com", "alex@example.com", PASSWORD
        )

    def setUp(self):
        self.client.force_login(self.user)


class ChangePasswordTests(AccountData, TestCase):
    """The My account page has a change-password form."""

    url = reverse_lazy("accounts:account")

    def change(self, old=PASSWORD, new=NEW_PASSWORD, confirm=None):
        return self.client.post(
            self.url,
            {
                "old_password": old,
                "new_password1": new,
                "new_password2": new if confirm is None else confirm,
            },
        )

    def test_page_shows_the_form_and_delete_link(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alex@example.com")
        for name in ("old_password", "new_password1", "new_password2"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, f'href="{reverse("accounts:delete")}"')

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:signin')}?next={self.url}")

    def test_correct_current_password_changes_it_and_stays_signed_in(self):
        response = self.change()

        # Don't fetch the target here: it would use up the one-time message.
        self.assertRedirects(response, str(self.url), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        page = self.client.get(self.url)
        self.assertContains(page, "Your password was changed.")

    def test_wrong_current_password_changes_nothing(self):
        response = self.change(old="not-the-password")

        self.assertEqual(response.status_code, 200)
        self.assertIn("old_password", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_weak_new_password_is_rejected_with_the_reason(self):
        response = self.change(new="12345678")

        self.assertContains(response, "too common")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_new_passwords_must_match(self):
        response = self.change(confirm="something-else-42")

        self.assertIn("new_password2", response.context["form"].errors)

    def test_can_sign_in_with_the_new_password(self):
        self.change()
        self.client.logout()

        response = self.client.post(
            reverse("accounts:signin"),
            {"username": "alex@example.com", "password": NEW_PASSWORD},
        )

        self.assertRedirects(response, reverse("zones:map"))


class DeleteAccountTests(AccountData, TestCase):
    """Deleting the account asks for confirmation, then signs out."""

    url = reverse_lazy("accounts:delete")

    def test_page_asks_for_confirmation(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This cannot be undone")
        self.assertContains(response, 'name="password"')
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_guest_is_sent_to_sign_in(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:signin')}?next={self.url}")

    def test_wrong_password_deletes_nothing(self):
        response = self.client.post(self.url, {"password": "not-the-password"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The password is incorrect.")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_missing_password_deletes_nothing(self):
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_confirmed_delete_removes_user_signs_out_and_goes_to_map(self):
        response = self.client.post(self.url, {"password": PASSWORD})

        self.assertRedirects(response, reverse("zones:map"))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, f'href="{reverse("accounts:signin")}"')

    def test_deleted_user_cannot_sign_in_again(self):
        self.client.post(self.url, {"password": PASSWORD})

        response = self.client.post(
            reverse("accounts:signin"),
            {"username": "alex@example.com", "password": PASSWORD},
        )

        self.assertContains(response, "The email or password is incorrect.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_can_sign_up_again_after_deletion(self):
        self.client.post(self.url, {"password": PASSWORD})

        response = self.client.post(
            reverse("accounts:signup"),
            {
                "email": "alex@example.com",
                "password1": NEW_PASSWORD,
                "password2": NEW_PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("zones:map"))


class UserDataCascadeTests(TestCase):
    """Deleting a user must delete everything that belongs to them. Saved
    routes (US13) and plans (US17) will link to the user; this fails the
    build if any model links to a user without on_delete=CASCADE."""

    def user_links(self):
        for model in apps.get_models():
            if model._meta.app_label in ("admin", "auth"):
                continue  # Django's own tables
            for field in model._meta.get_fields():
                if (
                    isinstance(field, (models.ForeignKey, models.OneToOneField))
                    and field.related_model is User
                ):
                    yield model, field

    def test_every_link_to_a_user_uses_cascade(self):
        for model, field in self.user_links():
            with self.subTest(model=model.__name__, field=field.name):
                self.assertIs(field.remote_field.on_delete, models.CASCADE)

    def test_user_model_is_django_builtin(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "auth.User")
