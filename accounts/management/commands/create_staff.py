"""US39 #113: create a staff account that can sign in to the admin.

The password is only ever typed at the prompt (twice, not shown), so no
staff password, username or email is written in the code, settings,
migrations, fixtures or docs."""

import getpass
import sys

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

User = get_user_model()

EMAIL_MAX_LENGTH = 150  # User.username's max length, as in sign-up (US10)


def clean_email(value):
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise CommandError(f"Enter a valid email address (got {value!r}).")
    if len(email) > EMAIL_MAX_LENGTH:
        raise CommandError(f"The email can be at most {EMAIL_MAX_LENGTH} characters.")
    return email


class Command(BaseCommand):
    help = (
        "Create a staff account (admin) that can sign in to /admin/. Asks for "
        "the email (unless --email is given) and for the password, which is "
        "never an option. Use --existing to make an account that already "
        "exists a staff account."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", help="The staff member's email address.")
        parser.add_argument(
            "--existing",
            action="store_true",
            help="Make an existing account staff. Its password is not changed.",
        )

    def handle(self, *args, email=None, existing=False, **options):
        if not sys.stdin.isatty():
            raise CommandError(
                "Run this in a terminal: it asks for the password and never "
                "reads it from a file, pipe or option."
            )
        email = clean_email(email if email is not None else input("Email: "))
        user = User.objects.filter(username=email).first()

        if existing:
            if user is None:
                raise CommandError(f"No account with the email {email}.")
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(
                f"{email} is now a staff account. The password is unchanged."
            )
            return

        if user is not None:
            raise CommandError(
                f"An account with the email {email} already exists. Run again "
                "with --existing to make it a staff account."
            )

        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password (again): "):
            raise CommandError("The two passwords do not match. Nothing was saved.")
        if not password:
            raise CommandError("Enter a password. Nothing was saved.")
        try:
            password_validation.validate_password(
                password, User(username=email, email=email)
            )
        except ValidationError as error:
            raise CommandError(" ".join(error.messages) + " Nothing was saved.")

        User.objects.create_superuser(username=email, email=email, password=password)
        self.stdout.write(
            f"{email} is now a staff account. Sign in at /admin/ with this email."
        )
