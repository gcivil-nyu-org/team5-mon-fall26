"""US11 #40: Sign In and Sign Out."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse, reverse_lazy

User = get_user_model()

PASSWORD = "taxi-route-7319"
GENERIC_ERROR = "The email or password is incorrect."


class AccountData:
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alex@example.com", "alex@example.com", PASSWORD
        )


class SignInTests(AccountData, TestCase):
    """GET and POST /accounts/signin/."""

    url = reverse_lazy("accounts:signin")

    def sign_in(self, email="alex@example.com", password=PASSWORD, **extra):
        return self.client.post(
            self.url, {"username": email, "password": password}, **extra
        )

    def test_page_shows_email_and_password_fields(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, f'href="{reverse("accounts:signup")}"')

    def test_correct_details_sign_in_and_go_to_the_map(self):
        response = self.sign_in()

        self.assertRedirects(response, reverse("zones:map"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_email_is_not_case_sensitive(self):
        response = self.sign_in(email="  ALEX@Example.com ")

        self.assertRedirects(response, reverse("zones:map"))

    def test_wrong_password_and_unknown_email_get_the_same_error(self):
        wrong_password = self.sign_in(password="not-the-password")
        unknown_email = self.sign_in(email="nobody@example.com")

        for response in (wrong_password, unknown_email):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, GENERIC_ERROR)
            self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(
            wrong_password.context["form"].errors,
            unknown_email.context["form"].errors,
        )

    def test_inactive_user_gets_the_same_generic_error(self):
        self.user.is_active = False
        self.user.save()

        response = self.sign_in()

        self.assertContains(response, GENERIC_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signed_in_user_is_sent_to_the_map(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("zones:map"))

    def test_next_to_another_site_is_ignored(self):
        response = self.client.post(
            f"{self.url}?next=https://evil.example.com/",
            {"username": "alex@example.com", "password": PASSWORD},
        )

        self.assertRedirects(response, reverse("zones:map"))


class SignOutTests(AccountData, TestCase):
    """POST /accounts/signout/."""

    url = reverse_lazy("accounts:signout")

    def test_sign_out_returns_to_the_map_as_a_guest(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url)

        self.assertRedirects(response, reverse("zones:map"))
        self.assertNotIn("_auth_user_id", self.client.session)
        page = self.client.get(reverse("zones:map"))
        self.assertContains(page, f'href="{reverse("accounts:signin")}"')

    def test_get_does_not_sign_out(self):
        # Signing out changes state, so it needs a POST with a CSRF token.
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)


class MapHeaderTests(AccountData, TestCase):
    """The header shows the account state."""

    def test_guest_sees_sign_in_and_sign_up(self):
        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, f'href="{reverse("accounts:signin")}"')
        self.assertContains(response, f'href="{reverse("accounts:signup")}"')

    def test_signed_in_user_sees_email_account_link_and_sign_out(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("zones:map"))

        self.assertContains(response, "alex@example.com")
        self.assertContains(response, f'href="{reverse("accounts:account")}"')
        self.assertContains(response, f'action="{reverse("accounts:signout")}"')
        self.assertContains(response, "Sign out")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, f'href="{reverse("accounts:signin")}"')


class SignInRequiredTests(AccountData, TestCase):
    """Pages that need an account send guests to sign in, then back."""

    url = reverse_lazy("accounts:account")

    def test_guest_is_sent_to_sign_in_with_next(self):
        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:signin')}?next={self.url}")

    def test_after_sign_in_the_guest_is_back_on_that_page(self):
        response = self.client.post(
            f"{reverse('accounts:signin')}?next={self.url}",
            {"username": "alex@example.com", "password": PASSWORD},
        )

        self.assertRedirects(response, str(self.url))

    def test_signed_in_user_sees_the_page(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alex@example.com")


class CsrfTests(AccountData, TestCase):
    """Every account form is protected by Django's CSRF check."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_forms_without_a_token_are_rejected(self):
        self.client.force_login(self.user)
        posts = {
            "accounts:signout": {},
            "accounts:signin": {"username": "alex@example.com", "password": PASSWORD},
            "accounts:signup": {"email": "new@example.com"},
        }
        for name, data in posts.items():
            with self.subTest(name=name):
                response = self.client.post(reverse(name), data)

                self.assertEqual(response.status_code, 403)

    def test_forms_include_a_token(self):
        for name in ("accounts:signin", "accounts:signup"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))

                self.assertContains(response, "csrfmiddlewaretoken")
