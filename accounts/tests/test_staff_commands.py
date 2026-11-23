"""US39 #113: create_staff and remove_staff.

Staff accounts are made by a command that asks for the password in the
terminal, so no staff password, username or email is ever in the code,
settings, migrations, fixtures or docs. These tests use example.com
addresses only."""

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

User = get_user_model()

PASSWORD = "taxi-route-7319"
GETPASS = "accounts.management.commands.create_staff.getpass.getpass"
INPUT = "builtins.input"
ISATTY = "accounts.management.commands.create_staff.sys.stdin.isatty"


def run(command, *args, **options):
    out = StringIO()
    call_command(command, *args, stdout=out, **options)
    return out.getvalue()


@mock.patch(ISATTY, return_value=True)
class CreateStaffTests(TestCase):
    def create(self, passwords=(PASSWORD, PASSWORD), **options):
        with mock.patch(GETPASS, side_effect=list(passwords)) as getpass:
            output = run("create_staff", **options)
        return output, getpass

    def test_creates_a_staff_account_from_the_prompts(self, _isatty):
        with mock.patch(INPUT, return_value="  Staff@Example.com "):
            output, getpass = self.create()

        user = User.objects.get()
        self.assertEqual(user.username, "staff@example.com")
        self.assertEqual(user.email, "staff@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(getpass.call_count, 2)
        self.assertIn("staff@example.com is now a staff account", output)
        self.assertNotIn(PASSWORD, output)

    def test_email_can_be_given_as_an_option(self, _isatty):
        with mock.patch(INPUT) as asked:
            self.create(email="staff@example.com")

        asked.assert_not_called()
        self.assertTrue(User.objects.get().is_staff)

    def test_the_password_is_never_an_option(self, _isatty):
        with self.assertRaises(TypeError):
            run("create_staff", email="staff@example.com", password=PASSWORD)

    def test_refuses_without_a_terminal(self, isatty):
        isatty.return_value = False

        with self.assertRaisesMessage(CommandError, "terminal"):
            self.create(email="staff@example.com")
        self.assertFalse(User.objects.exists())

    def test_refuses_an_invalid_email(self, _isatty):
        for email in ("", "not-an-email", "a" * 140 + "@example.com"):
            with self.subTest(email=email):
                with self.assertRaisesMessage(CommandError, "email"):
                    self.create(email=email)
        self.assertFalse(User.objects.exists())

    def test_refuses_passwords_that_do_not_match(self, _isatty):
        with self.assertRaisesMessage(CommandError, "do not match"):
            self.create(passwords=(PASSWORD, "something-else-42"), email="s@e.com")
        self.assertFalse(User.objects.exists())

    def test_refuses_a_weak_password(self, _isatty):
        for weak in ("", "short", "12345678901", "password123"):
            with self.subTest(password=weak):
                with self.assertRaises(CommandError):
                    self.create(passwords=(weak, weak), email="staff@example.com")
        self.assertFalse(User.objects.exists())

    def test_refuses_an_email_that_already_has_an_account(self, _isatty):
        User.objects.create_user("rider@example.com", "rider@example.com", "x")

        with self.assertRaisesMessage(CommandError, "--existing"):
            self.create(email="RIDER@example.com")

        self.assertFalse(User.objects.get().is_staff)

    def test_existing_makes_an_account_staff_and_keeps_its_password(self, _isatty):
        User.objects.create_user("rider@example.com", "rider@example.com", PASSWORD)

        output, getpass = self.create(email="rider@example.com", existing=True)

        user = User.objects.get()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        getpass.assert_not_called()
        self.assertIn("password is unchanged", output)

    def test_existing_needs_the_account_to_exist(self, _isatty):
        with self.assertRaisesMessage(CommandError, "No account"):
            self.create(email="nobody@example.com", existing=True)


class RemoveStaffTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(
            "staff@example.com", "staff@example.com", PASSWORD
        )

    def test_takes_away_staff_rights_and_keeps_the_account(self):
        output = run("remove_staff", email=" Staff@Example.com")

        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_staff)
        self.assertFalse(self.staff.is_superuser)
        self.assertTrue(self.staff.check_password(PASSWORD))
        self.assertIn("no longer a staff account", output)

    def test_takes_effect_on_the_next_admin_request(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

        run("remove_staff", email="staff@example.com")

        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_unknown_email(self):
        with self.assertRaisesMessage(CommandError, "No account"):
            run("remove_staff", email="nobody@example.com")

    def test_account_that_is_not_staff(self):
        User.objects.create_user("rider@example.com", "rider@example.com", "x")

        output = run("remove_staff", email="rider@example.com")

        self.assertIn("is not a staff account", output)

    def test_email_is_required(self):
        with self.assertRaises(CommandError):
            run("remove_staff")
